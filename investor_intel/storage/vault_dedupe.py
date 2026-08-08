"""같은 문서 id로 vault에 여러 사본이 생긴 경우를 찾아 하나만 남긴다.

중복이 쌓인 원인은 두 가지였다(둘 다 `persist_collect_result`에서 수집 시점에 막았지만,
이미 만들어진 사본은 이 모듈로 따로 정리해야 한다):

1. `path_for_document`가 파일명을 `published_at`으로 만드는데 central_bank 컬렉터는
   회의록이 늦게 공개돼도 recency 창에 걸리도록 `published_at=now`를 쓴다 - 재수집할 때마다
   같은 문서가 새 날짜의 파일로 저장됐다(같은 디렉터리 안 중복).
2. content_hash로 중복이 잡히면 기존 id를 재사용하지만 경로는 새 컬렉터의 `source_name`으로
   만들어져, 같은 id가 다른 소스 폴더에 한 벌 더 생겼다(예: IB/naver ↔ IB/naver-weekly-hot).
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from investor_intel.models.source_document import SourceDocument
from investor_intel.storage.obsidian_repo import (
    list_documents,
    parse_document,
    resolve_document_path,
)

# analyze 파이프라인이 본문에 끼워 넣는 섹션(claims_splice). frontmatter의 llm_processed와
# 함께 "이 사본은 이미 분석됐다"는 표시로 쓴다 - 분석된 사본을 지우면 LLM 비용을 들여 만든
# 결과가 사라지고 재분석까지 하게 된다.
_ANALYSIS_HEADER = "## 핵심 주장"

_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-(?P<id>.+)\.md$")


@dataclass
class DuplicateGroup:
    doc_id: str
    keep: Path
    remove: list[Path]

    @property
    def freed_bytes(self) -> int:
        return sum(path.stat().st_size for path in self.remove if path.exists())


@dataclass
class DedupeReport:
    groups: list[DuplicateGroup] = field(default_factory=list)
    # 서로 다른 분석 결과가 여러 사본에 있어 손대지 않은 그룹의 문서 id.
    protected: list[str] = field(default_factory=list)
    # frontmatter를 읽지 못한 파일 (path, 사유).
    unparsed: list[tuple[Path, str]] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    freed_bytes: int = 0
    # DB의 file_path가 남긴 사본을 가리키지 않아 고쳐 쓴 문서 id.
    repointed: list[str] = field(default_factory=list)


def _candidate_paths(vault_path: Path) -> dict[str, list[Path]]:
    """파일명의 id 부분으로 먼저 후보를 좁힌다.

    vault에는 md가 수만 개라 전부 YAML 파싱하면 느리다. 파일명은 `<날짜>-<doc.id>.md`이므로
    id가 겹치는 후보만 골라낸 뒤 그 파일들만 실제로 파싱해 frontmatter id로 다시 묶는다.
    """
    by_name_id: dict[str, list[Path]] = defaultdict(list)
    for path in list_documents(vault_path):
        match = _FILENAME_RE.match(path.name)
        if match is not None:
            by_name_id[match.group("id")].append(path)
    return {key: paths for key, paths in by_name_id.items() if len(paths) > 1}


def _load(path: Path) -> tuple[SourceDocument, str]:
    return parse_document(path.read_text(encoding="utf-8"))


def _is_analyzed(entry: tuple[SourceDocument, str]) -> bool:
    doc, body = entry
    return doc.llm_processed or _ANALYSIS_HEADER in body


def _pick_keep(
    conn: sqlite3.Connection,
    vault_path: Path,
    doc_id: str,
    parsed: dict[Path, tuple[SourceDocument, str]],
    pool: list[Path],
) -> tuple[Path, bool]:
    """`pool` 중 남길 사본과, DB의 file_path를 고쳐 써야 하는지 여부를 반환한다."""
    row = conn.execute("SELECT file_path FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if row is not None:
        indexed = resolve_document_path(vault_path, row["file_path"])
        if indexed is not None:
            for path in pool:
                if path.resolve() == indexed.resolve():
                    return path, False

    # DB가 가리키는 사본이 pool에 없으면 published_at이 가장 최신인 사본을 남긴다 -
    # `reindex()`가 경로 정렬 순으로 덮어쓸 때 살아남는 사본과 같은 선택이다.
    newest = max(pool, key=lambda path: (parsed[path][0].published_at, str(path)))
    return newest, True


def plan_dedupe(vault_path: Path, conn: sqlite3.Connection) -> DedupeReport:
    """중복 사본을 찾아 정리 계획만 만든다(파일/DB는 건드리지 않는다)."""
    report = DedupeReport()

    for paths in _candidate_paths(vault_path).values():
        parsed_by_id: dict[str, dict[Path, tuple[SourceDocument, str]]] = defaultdict(dict)
        for path in paths:
            try:
                doc, body = _load(path)
            except Exception as exc:  # noqa: BLE001
                report.unparsed.append((path, str(exc)))
                continue
            parsed_by_id[doc.id][path] = (doc, body)

        for doc_id, parsed in parsed_by_id.items():
            if len(parsed) < 2:
                continue

            # 분석된 사본이 있으면 그쪽을 우선 남긴다. DB가 미분석 사본을 가리키고 있으면
            # 그걸 남기는 순간 LLM 비용을 들여 만든 결과를 버리고 재분석까지 하게 된다.
            analyzed = [path for path, entry in parsed.items() if _is_analyzed(entry)]
            if len({parsed[path][1] for path in analyzed}) > 1:
                # 서로 다른 분석 결과가 여러 벌 있으면 무엇을 버릴지 기계적으로 못 정한다.
                report.protected.append(doc_id)
                continue

            keep, repointed = _pick_keep(conn, vault_path, doc_id, parsed, analyzed or list(parsed))
            remove = sorted(path for path in parsed if path != keep)

            report.groups.append(DuplicateGroup(doc_id=doc_id, keep=keep, remove=remove))
            if repointed:
                report.repointed.append(doc_id)

    report.groups.sort(key=lambda group: str(group.keep))
    report.freed_bytes = sum(group.freed_bytes for group in report.groups)
    return report


def apply_dedupe(vault_path: Path, conn: sqlite3.Connection, report: DedupeReport) -> DedupeReport:
    """계획대로 중복 사본을 지우고, DB의 file_path를 남긴 사본으로 맞춘다."""
    repointed = set(report.repointed)
    emptied: set[Path] = set()
    for group in report.groups:
        for path in group.remove:
            if path.exists():
                path.unlink()
                report.removed.append(path)
                emptied.add(path.parent)
        if group.doc_id in repointed:
            conn.execute(
                "UPDATE documents SET file_path = ? WHERE id = ?",
                (str(group.keep.relative_to(vault_path)), group.doc_id),
            )
    conn.commit()
    _prune_empty_dirs(vault_path, emptied)
    return report


def _prune_empty_dirs(vault_path: Path, directories: set[Path]) -> None:
    """사본을 전부 지워 빈 껍데기만 남은 소스 폴더를 치운다(10_Sources 위로는 올라가지 않는다)."""
    sources_dir = vault_path / "10_Sources"
    for directory in directories:
        current = directory
        while current != sources_dir and sources_dir in current.parents:
            if any(current.iterdir()):
                break
            current.rmdir()
            current = current.parent

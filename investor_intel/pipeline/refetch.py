"""본문이 불완전한 문서를 다시 가져온다.

## 왜 별도 경로가 필요한가

수집기는 증분 체크포인트(`last_seen_id` / `last_accession_number`)로 앞으로만 간다. 그래서
과거에 불완전하게 저장된 문서는 **아무리 collect를 다시 돌려도 손대지 않는다.** 실측:

    SEC          396건 중 355건(90%)이 본문 미확보 - 이유: "not parsed in this phase"
    DART       1,362건 중 1,059건(78%)  같음
    DART 인코딩 깨짐 211건               - 원문을 UTF-8로 잘못 디코딩해 저장
    본문 절단   329건                    - 40,000자 상한

이유 문구가 "this phase"인 것에서 보이듯 대부분 **본문 수집 기능이 붙기 전에 모은 문서**다.
기능은 이미 있는데 되돌아갈 길이 없었다. 그 길을 만드는 것이 이 모듈이다.

## 두 가지 전략

1. **제자리 재수집** (DART). 접수번호만 있으면 원문을 다시 받을 수 있으므로, 인덱스가 대상
   목록을 주고 문서를 그 자리에서 갱신한다. 파일 경로·문서 id·수집 시각을 그대로 두고
   본문과 `content_hash`만 바뀐다.
2. **체크포인트 되감기** (그 외). SEC 공시처럼 원문 위치를 알아내려면 수집기의 필링 조회
   로직 전체가 필요한 경우, 그 로직을 복제하지 않는다 - 대신 해당 수집기의 체크포인트를
   되감아 다음 `collect --backfill-days`가 과거를 다시 훑게 한다. 이미 완전한 문서는
   `persist_collect_result`의 content_hash 비교에서 그대로 건너뛰어진다.

복제하지 않는 이유는 명확하다. 재수집 경로가 수집 경로와 갈라지면, 둘 중 하나만 고쳐진
버그가 생긴다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from investor_intel.collectors.dart_client import DartClient
from investor_intel.collectors.dart_document import render_dart_filing_body
from investor_intel.collectors.dart_document_fetch import fetch_full_text
from investor_intel.collectors.dart_filings_parser import DartFilingRef
from investor_intel.ingest.quality import CORRUPT_RATIO_THRESHOLD, readable_ratio, truncation_of
from investor_intel.models.common import ContentCaptureMode
from investor_intel.models.source_document import ContentCapture, SourceDocument
from investor_intel.storage.content_hash import compute_content_hash
from investor_intel.storage.obsidian_repo import (
    read_document,
    resolve_document_path,
    write_document_at,
)
from investor_intel.storage.sqlite_index import upsert_document

# 재수집이 필요한 이유. 세 이유가 서로 다른 조치를 요구하므로 섞지 않는다.
REASONS = ("stub", "corrupt", "truncated")

# 제자리 재수집이 가능한 소스. 나머지는 체크포인트 되감기로 처리한다.
IN_PLACE_SOURCE_TYPES = ("dart",)


@dataclass
class RefetchTarget:
    doc_id: str
    source_type: str
    source_name: str
    file_path: str
    accession_number: str | None
    reason: str


@dataclass
class RefetchPlan:
    targets: list[RefetchTarget] = field(default_factory=list)

    def by_reason(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for target in self.targets:
            out[target.reason] = out.get(target.reason, 0) + 1
        return out

    def by_source_type(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for target in self.targets:
            out[target.source_type] = out.get(target.source_type, 0) + 1
        return out

    def in_place(self) -> list[RefetchTarget]:
        return [t for t in self.targets if t.source_type in IN_PLACE_SOURCE_TYPES]

    def needs_rewind(self) -> list[RefetchTarget]:
        return [t for t in self.targets if t.source_type not in IN_PLACE_SOURCE_TYPES]


def plan_refetch(
    conn: sqlite3.Connection,
    reasons: Sequence[str] = REASONS,
    source_types: Sequence[str] | None = None,
    limit: int | None = None,
) -> RefetchPlan:
    """카탈로그에서 재수집 대상을 고른다.

    `enrich-vault`가 채워 둔 `capture_mode` / `readable_ratio` / `truncated` 컬럼을 쓴다.
    이 컬럼이 없으면 대상을 고르려고 vault 4,818건을 매번 다시 파싱해야 했다.
    """
    clauses: list[str] = []
    params: list = []
    if "stub" in reasons:
        clauses.append("capture_mode != 'full'")
    if "corrupt" in reasons:
        clauses.append("readable_ratio < ?")
        params.append(1.0 - CORRUPT_RATIO_THRESHOLD)
    if "truncated" in reasons:
        clauses.append("truncated = 1")
    if not clauses:
        return RefetchPlan()

    sql = f"SELECT * FROM documents WHERE ({' OR '.join(clauses)})"
    if source_types:
        placeholders = ",".join("?" * len(source_types))
        sql += f" AND source_type IN ({placeholders})"
        params.extend(source_types)
    # 오래된 것부터. 최근 문서는 다음 정기 수집에서 자연히 다시 다뤄질 여지가 있다.
    sql += " ORDER BY published_at"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"

    plan = RefetchPlan()
    for row in conn.execute(sql, params):
        # 한 문서가 여러 이유에 걸릴 수 있다. 조치가 가장 무거운 것을 대표 이유로 삼는다.
        if row["capture_mode"] != "full":
            reason = "stub"
        elif row["readable_ratio"] < 1.0 - CORRUPT_RATIO_THRESHOLD:
            reason = "corrupt"
        else:
            reason = "truncated"
        plan.targets.append(
            RefetchTarget(
                doc_id=row["id"], source_type=row["source_type"],
                source_name=row["source_name"], file_path=row["file_path"],
                accession_number=row["accession_number"], reason=reason,
            )
        )
    return plan


@dataclass
class RefetchResult:
    attempted: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    readable_before: float = 0.0
    readable_after: float = 0.0


def _dart_ref(doc: SourceDocument, filing_date: date) -> DartFilingRef:
    """저장된 문서에서 DART 필링 참조를 되만든다.

    본문 렌더링에 쓰이는 것은 corp_name / report_nm / rcept_dt / rcept_no / flr_nm 다섯
    개다. 전부 frontmatter에 있으므로 DART 목록 API를 다시 부르지 않아도 된다.
    """
    return DartFilingRef(
        rcept_no=str(doc.accession_number or ""),
        rcept_dt=filing_date,
        report_nm=str(doc.filing_type or ""),
        corp_name=str(doc.author or doc.source_name),
        corp_code="",
        flr_nm=str(doc.author or doc.source_name),
        corp_cls="",
    )


def refetch_dart_documents(
    targets: Sequence[RefetchTarget],
    vault_path: Path,
    conn: sqlite3.Connection,
    client: DartClient,
    api_key: str,
    apply: bool = False,
) -> RefetchResult:
    """DART 문서를 제자리에서 다시 받아 본문을 갈아끼운다.

    파일 경로와 문서 id는 그대로 둔다 - 경로가 바뀌면 같은 문서의 사본이 하나 더 생긴다
    (`write_document`가 published_at으로 파일명을 만들기 때문이다).
    """
    result = RefetchResult()
    for target in targets:
        if not target.accession_number:
            result.failed += 1
            result.errors.append(f"{target.doc_id}: 접수번호가 없어 원문을 특정할 수 없음")
            continue
        path = resolve_document_path(vault_path, target.file_path)
        if path is None:
            result.failed += 1
            result.errors.append(f"{target.doc_id}: vault에서 파일을 찾을 수 없음")
            continue

        result.attempted += 1
        try:
            doc, old_body = read_document(path)
            full_text = fetch_full_text(client, api_key, target.accession_number)
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            result.errors.append(f"{target.doc_id}: {exc}")
            continue

        if full_text is None:
            result.failed += 1
            result.errors.append(f"{target.doc_id}: 원문을 받지 못함 (metadata_only 유지)")
            continue

        body = render_dart_filing_body(
            _dart_ref(doc, doc.published_at.date()), doc.source_url, full_text=full_text
        )
        before = readable_ratio(old_body)
        after = readable_ratio(body)
        result.readable_before += before
        result.readable_after += after

        content_hash = compute_content_hash(body)
        if content_hash == doc.content_hash:
            result.unchanged += 1
            continue

        truncated, original_chars = truncation_of(body)
        updated = doc.model_copy(
            update={
                "content_hash": content_hash,
                "content_capture": ContentCapture(mode=ContentCaptureMode.FULL),
                "readable_ratio": after,
                "truncated": truncated,
                "original_chars": original_chars,
                "updated_at": datetime.now(UTC),
                # 본문이 바뀌었으니 기존 분석 결과는 낡았다.
                "llm_processed": False,
                "llm_model": None,
                "llm_prompt_version": None,
            }
        )
        result.updated += 1
        if apply:
            write_document_at(path, updated, body)
            upsert_document(
                conn, updated, file_path=str(path.relative_to(vault_path)),
                source_specific_id=updated.source_specific_id,
            )
    return result


def rewind_checkpoints(
    conn: sqlite3.Connection, source_ids: Sequence[str], apply: bool = False
) -> int:
    """수집기 체크포인트를 되감아 다음 backfill이 과거를 다시 훑게 한다.

    이미 완전한 문서는 `persist_collect_result`가 content_hash 비교로 건너뛴다 - 파일도
    DB도 건드리지 않는다. 그래서 되감기의 비용은 네트워크 요청뿐이다.
    """
    if not apply or not source_ids:
        return len(source_ids)
    conn.executemany(
        "UPDATE collector_state SET last_seen_id = NULL, last_accession_number = NULL, "
        "backfill_completed = 0 WHERE source_id = ?",
        [(source_id,) for source_id in source_ids],
    )
    conn.commit()
    return len(source_ids)


def collector_source_ids(targets: Sequence[RefetchTarget]) -> list[str]:
    """대상 문서를 만든 수집기의 source_id를 되만든다.

    수집기는 `<source_type>_<source_name>` 규칙으로 source_id를 만든다(13F는
    `sec_13f_<investor id>`). 카탈로그에는 source_id가 없으므로 조합해 맞춘다.
    """
    ids = {f"{t.source_type}_{t.source_name}" for t in targets}
    return sorted(ids)

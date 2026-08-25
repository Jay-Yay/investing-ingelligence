from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import yaml

from investor_intel.indexing.text_normalize import normalize

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)

# 수집기가 문서마다 동일하게 붙이는 고정 안내문. 내용은 문서가 아니라 컬렉터에 대한
# 설명이라 검색 대상이 아니고, 청크 단위로 자르면 '안내문만 들어있는 청크'가 생겨
# 검색 결과를 오염시킨다.
_DISCLAIMER_HEADINGS = ("유의사항",)

# analyze 단계가 채우는 자리표시자 섹션. 아직 비어 있으면 색인할 내용이 없다.
_ANALYSIS_SECTIONS = ("핵심 주장", "근거", "반대 근거", "언급 자산", "포트폴리오 관련성")


@dataclass
class Section:
    heading: str
    text: str


@dataclass
class LoadedDocument:
    doc_id: str
    path: str
    source_type: str
    source_name: str
    title: str
    author: str
    published_at: str
    language: str
    document_type: str
    filing_type: str | None
    reporting_period: str | None
    accession_number: str | None
    companies: list[str]
    capture_mode: str
    source_url: str
    # 수집 시점에 확정된 값들(`ingest` 계층). 옛 문서에는 없어서 기본값이 쓰인다 -
    # `enrich-vault`로 채울 수 있다.
    readable_ratio: float = 1.0
    truncated: bool = False
    mentions: list[str] = field(default_factory=list)
    analyst_house: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    dropped_boilerplate_chars: int = 0

    @property
    def body(self) -> str:
        return "\n\n".join(f"## {s.heading}\n{s.text}" for s in self.sections)

    @property
    def has_body(self) -> bool:
        return self.capture_mode != "metadata_only" and bool(self.body.strip())


def _split_sections(body: str) -> list[Section]:
    out: list[Section] = []
    parts = re.split(r"^## ", body, flags=re.M)
    if parts and parts[0].strip():
        out.append(Section("", parts[0].strip()))
    for part in parts[1:]:
        head, _, rest = part.partition("\n")
        out.append(Section(head.strip(), rest.strip()))
    return out


def parse_markdown(path: Path, strip_boilerplate: bool) -> LoadedDocument | None:
    raw = path.read_text(encoding="utf-8")
    m = _FRONTMATTER.match(raw)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    sections = _split_sections(raw[m.end() :])

    dropped = 0
    if strip_boilerplate:
        kept: list[Section] = []
        for s in sections:
            is_disclaimer = any(k in s.heading for k in _DISCLAIMER_HEADINGS)
            is_empty_analysis = s.heading in _ANALYSIS_SECTIONS and not s.text.strip()
            if is_disclaimer or is_empty_analysis:
                dropped += len(s.heading) + len(s.text)
                continue
            kept.append(s)
        sections = kept

    sections = [Section(s.heading, normalize(s.text)) for s in sections if s.text.strip()]

    capture = fm.get("content_capture") or {}
    capture_mode = capture.get("mode", "unknown") if isinstance(capture, dict) else str(capture)
    entities = fm.get("entities") or {}
    if not isinstance(entities, dict):
        entities = {}

    return LoadedDocument(
        doc_id=str(fm.get("id") or path.stem),
        path=str(path),
        source_type=str(fm.get("source_type") or "unknown"),
        source_name=str(fm.get("source_name") or ""),
        title=str(fm.get("title") or ""),
        author=str(fm.get("author") or ""),
        published_at=str(fm.get("published_at") or ""),
        language=str(fm.get("language") or ""),
        document_type=str(fm.get("document_type") or ""),
        filing_type=fm.get("filing_type"),
        reporting_period=(str(fm["reporting_period"]) if fm.get("reporting_period") else None),
        accession_number=fm.get("accession_number"),
        companies=list(fm.get("companies") or []),
        capture_mode=capture_mode,
        source_url=str(fm.get("source_url") or ""),
        readable_ratio=float(fm.get("readable_ratio", 1.0) or 1.0),
        truncated=bool(fm.get("truncated") or False),
        mentions=list(entities.get("mentions") or []),
        analyst_house=list(entities.get("analyst_house") or []),
        sections=sections,
        dropped_boilerplate_chars=dropped,
    )


def load_vault(vault_path: Path, strip_boilerplate: bool = False) -> Iterator[LoadedDocument]:
    """vault/10_Sources 아래 모든 마크다운을 문서 객체로 읽어들인다.

    파일 경로(연도/소스명 디렉터리)가 아니라 frontmatter를 신뢰한다. 경로는 published_at이
    바뀌면 달라질 수 있지만 frontmatter의 id/content_hash는 문서를 따라다니기 때문이다.
    """
    root = vault_path / "10_Sources"
    for path in sorted(root.rglob("*.md")):
        doc = parse_markdown(path, strip_boilerplate)
        if doc is not None:
            yield doc

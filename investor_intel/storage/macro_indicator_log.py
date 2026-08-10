from __future__ import annotations

from datetime import datetime
from pathlib import Path

from investor_intel.models.macro import IndicatorSnapshot

_MACRO_DIR = "40_Analysis/Macro"
_DOC_HEADER_TEMPLATE = (
    "# {title}\n\n"
    "가설 ID: `{thesis_id}`\n\n"
    "이 파일은 `record-indicators` 명령으로 append된다. 같은 날짜+시각(분 단위) 섹션이 "
    "이미 있으면 덮어쓴다 - 중복 섹션이 쌓이지 않도록. 지표 정의(기준값/강세·약세 임계치)는 "
    "`config/macro_theses.yaml`을 참고.\n"
)


def _log_path(vault_path: Path, thesis_id: str) -> Path:
    return vault_path / _MACRO_DIR / f"{thesis_id}.md"


def _section_header(as_of: datetime) -> str:
    return f"## {as_of.strftime('%Y-%m-%d %H:%M')}"


def _render_entry(as_of: datetime, values: dict[str, IndicatorSnapshot]) -> str:
    lines = [_section_header(as_of), ""]
    for indicator_id, snap in values.items():
        lines.append(f"- {indicator_id}: {snap.value}")
        if snap.note:
            lines.append(f"  - note: {snap.note}")
        if snap.source_url:
            lines.append(f"  - source: {snap.source_url}")
    return "\n".join(lines) + "\n"


def _split_sections(content: str) -> tuple[str, list[str]]:
    """문서 헤더(첫 `## ` 이전)와 각 `## ` 섹션 본문(헤더 포함, 앞뒤 공백 제거) 리스트로 나눈다."""
    parts = content.split("\n## ")
    doc_header = parts[0].rstrip("\n")
    sections = [f"## {part}".strip() for part in parts[1:]]
    return doc_header, sections


def append_macro_snapshot(
    vault_path: Path,
    thesis_id: str,
    thesis_title: str,
    as_of: datetime,
    values: dict[str, IndicatorSnapshot],
) -> None:
    """지표 스냅샷을 vault/40_Analysis/Macro/<thesis_id>.md에 append한다.

    같은 날짜+시각(분) 섹션이 이미 있으면(같은 시점 재실행) 덮어쓴다.
    """
    path = _log_path(vault_path, thesis_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_section = _render_entry(as_of, values).strip()
    date_header = _section_header(as_of)

    if path.exists():
        doc_header, sections = _split_sections(path.read_text(encoding="utf-8"))
        sections = [s for s in sections if not s.startswith(date_header + "\n")]
    else:
        doc_header = _DOC_HEADER_TEMPLATE.format(title=thesis_title, thesis_id=thesis_id).rstrip(
            "\n"
        )
        sections = []

    sections.append(new_section)
    body = doc_header + "\n\n" + "\n\n".join(sections)
    path.write_text(body.strip() + "\n", encoding="utf-8")


def read_macro_history(vault_path: Path, thesis_id: str) -> list[tuple[str, dict[str, str]]]:
    """[(YYYY-MM-DD HH:MM, {indicator_id: value}), ...]를 기록된 순서(오래된 것부터)로 반환.

    로그가 없으면 빈 리스트.
    """
    path = _log_path(vault_path, thesis_id)
    if not path.exists():
        return []
    _doc_header, sections = _split_sections(path.read_text(encoding="utf-8"))
    history: list[tuple[str, dict[str, str]]] = []
    for section in sections:
        lines = section.splitlines()
        timestamp = lines[0].removeprefix("## ").strip()
        values: dict[str, str] = {}
        for line in lines[1:]:
            # 들여쓰기 없는 최상위 불릿만 지표 값 (note/source 줄은 2칸 들여쓰기라 제외됨)
            if line.startswith("- "):
                key, _, val = line[2:].partition(":")
                values[key.strip()] = val.strip()
        history.append((timestamp, values))
    return history

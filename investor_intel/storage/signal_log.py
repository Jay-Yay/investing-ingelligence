from __future__ import annotations

from datetime import date
from pathlib import Path

from investor_intel.models.analysis import PositionSignal

_SIGNAL_DIR = "40_Analysis/Claims"
_DOC_HEADER_TEMPLATE = (
    "# {symbol} 신호 로그\n\n"
    "이 파일은 포트폴리오 모니터가 매일 자동으로 append한다. 마지막 `## 날짜` 섹션이 다음 실행의 "
    '"전일까지의 핵심 판단" 입력으로 쓰이므로 직접 수정하지 않는 것을 권장한다.\n'
)


def _log_path(vault_path: Path, symbol: str) -> Path:
    return vault_path / _SIGNAL_DIR / f"{symbol}.md"


def _render_entry(as_of: date, signal_entry: PositionSignal) -> str:
    lines = [f"## {as_of.isoformat()}", ""]
    lines.append(f"- signal: {signal_entry.signal.value if signal_entry.signal else 'null'}")
    lines.append(f"- signal_strength: {signal_entry.signal_strength}")
    lines.append(f"- thesis_shift: {signal_entry.thesis_shift.value}")
    lines.append(f"- decision_status: {signal_entry.decision_status.value}")
    if signal_entry.new_facts:
        lines.append("- new_facts:")
        lines.extend(f"  - {fact}" for fact in signal_entry.new_facts)
    lines.append(f"- causal_chain: {signal_entry.causal_chain}")
    lines.append(f"- expectation_vs_price: {signal_entry.expectation_vs_price}")
    if signal_entry.counter_evidence:
        lines.append("- counter_evidence:")
        lines.extend(f"  - {item}" for item in signal_entry.counter_evidence)
    lines.append(f"- action_conditions: {signal_entry.action_conditions}")
    lines.append(f"- next_check_conditions: {signal_entry.next_check_conditions}")
    return "\n".join(lines) + "\n"


def _split_sections(content: str) -> tuple[str, list[str]]:
    """문서 헤더(첫 `## ` 이전)와 각 `## ` 섹션 본문(헤더 포함, 앞뒤 공백 제거) 리스트로 나눈다."""
    parts = content.split("\n## ")
    doc_header = parts[0].rstrip("\n")
    sections = [f"## {part}".strip() for part in parts[1:]]
    return doc_header, sections


def append_signal_log(vault_path: Path, symbol: str, as_of: date, signal_entry: PositionSignal) -> None:
    """오늘자 신호를 vault/40_Analysis/Claims/<symbol>.md에 append한다.

    같은 날짜 섹션이 이미 있으면(같은 날 재실행) 덮어쓴다 - 중복 섹션이 쌓이지 않도록.
    """
    path = _log_path(vault_path, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_section = _render_entry(as_of, signal_entry).strip()
    date_header = f"## {as_of.isoformat()}"

    if path.exists():
        doc_header, sections = _split_sections(path.read_text(encoding="utf-8"))
        sections = [s for s in sections if not s.startswith(date_header + "\n")]
    else:
        doc_header = _DOC_HEADER_TEMPLATE.format(symbol=symbol).rstrip("\n")
        sections = []

    sections.append(new_section)
    body = doc_header + "\n\n" + "\n\n".join(sections)
    path.write_text(body.strip() + "\n", encoding="utf-8")


def read_latest_signal_text(vault_path: Path, symbol: str) -> str | None:
    """가장 최근 `## 날짜` 섹션의 원문 텍스트를 반환한다. 로그가 없으면 None."""
    path = _log_path(vault_path, symbol)
    if not path.exists():
        return None
    _doc_header, sections = _split_sections(path.read_text(encoding="utf-8"))
    if not sections:
        return None
    return sections[-1].strip()

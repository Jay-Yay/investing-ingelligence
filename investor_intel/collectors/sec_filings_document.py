from __future__ import annotations

from investor_intel.collectors.sec_companyfacts import (
    FinancialFact,
    FinancialStatementSnapshot,
)
from investor_intel.collectors.sec_filings_parser import CompanyFilingRef
from investor_intel.models.config import CompanyConfig

_SNAPSHOT_LABELS: dict[str, str] = {
    "revenue": "매출",
    "net_income": "순이익",
    "total_assets": "총자산",
    "total_liabilities": "총부채",
}

SEC_FILING_LIMITATIONS_NOTE = (
    "- 이 공시는 특정 시점의 규제 공시이며 투자 자문이 아니다.\n"
    "- 10-K/10-Q/20-F는 primaryDocument HTML에서 텍스트를 추출해 전문을 캡처한다(태그만 제거한 "
    "단순 변환이라 표 구조가 완벽히 보존되진 않는다). 8-K/6-K는 첨부 exhibit 중 컨퍼런스콜 "
    "녹취록으로 보이는 것이 있으면 그 원문을, 없어도 실적 관련 필링이면(8-K 항목 2.02, 또는 "
    "period_of_report가 채워진 6-K) 실적 보도자료 exhibit 원문을 캡처한다 - 그 외(합병/임원변경 "
    "등 실적과 무관한 8-K/6-K)는 메타데이터와 원문 링크만 캡처한다.\n"
    "- 8-K 항목 코드는 사건의 주제를 나타낼 뿐 호재/악재 방향을 의미하지 않는다.\n"
    "- 외국민간발행인(FPI)의 6-K는 국내 기업의 8-K와 제출 주기 및 내용 기준이 달라 "
    "직접 비교할 수 없다.\n"
)


def _format_fact(fact: FinancialFact) -> str:
    return f"${fact.val:,.0f} (기간: {fact.end.isoformat()})"


def _render_financial_snapshot_section(snapshot: FinancialStatementSnapshot | None) -> list[str]:
    if snapshot is None:
        return []

    lines = [
        f"- {_SNAPSHOT_LABELS[field]}: {_format_fact(fact)}"
        for field, fact in (
            ("revenue", snapshot.revenue),
            ("net_income", snapshot.net_income),
            ("total_assets", snapshot.total_assets),
            ("total_liabilities", snapshot.total_liabilities),
        )
        if fact is not None
    ]
    if not lines:
        return []

    return ["## 재무 데이터 (XBRL)", "", *lines, ""]


_BODY_NOTE_BY_CAPTURE_KIND: dict[str, str] = {
    "transcript": "(첨부 컨퍼런스콜 녹취록 원문)",
    "press_release": "(첨부 실적발표 보도자료 원문)",
    "primary_document": "(primaryDocument에서 추출한 원문 전체)",
}


def render_sec_filing_body(
    filing: CompanyFilingRef,
    company: CompanyConfig,
    canonical_url: str,
    snapshot: FinancialStatementSnapshot | None = None,
    full_text: str | None = None,
    capture_kind: str | None = None,
) -> str:
    period = filing.period_of_report.isoformat() if filing.period_of_report else "해당 없음"
    items_line = (
        f"{filing.form} 항목 코드: {', '.join(filing.items)}"
        if filing.items
        else f"{filing.form} 항목 코드: 해당 없음"
    )
    body_note = _BODY_NOTE_BY_CAPTURE_KIND.get(capture_kind) if full_text and capture_kind else None

    sections = [
        "## 원문",
        "",
        f"{company.name} ({company.ticker}) {filing.form} — "
        f"보고 기준일 {period}, "
        f"제출일 {filing.filing_date.isoformat()}, "
        f"accession {filing.accession_number}",
        *([body_note] if body_note else []),
        "",
        items_line,
        "",
        *([full_text] if full_text else []),
        "",
        *_render_financial_snapshot_section(snapshot),
        "## 공시 해석 시 유의사항",
        "",
        SEC_FILING_LIMITATIONS_NOTE,
        "## 핵심 주장",
        "",
        "## 근거",
        "",
        "## 반대 근거",
        "",
        "## 언급 자산",
        "",
        f"{company.name} ({company.ticker}) {filing.form} 공시.",
        "",
        "## 포트폴리오 관련성",
        "",
        "## 출처",
        "",
        f"- [원문]({canonical_url})",
        "",
    ]
    return "\n".join(sections)

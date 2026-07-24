from __future__ import annotations

from investor_intel.collectors.sec_filings_parser import CompanyFilingRef
from investor_intel.models.config import CompanyConfig

SEC_FILING_LIMITATIONS_NOTE = (
    "- 이 공시는 특정 시점의 규제 공시이며 투자 자문이 아니다.\n"
    "- 원문 전체 텍스트는 이 단계에서 수집하지 않으며, 메타데이터와 원문 링크만 캡처한다.\n"
    "- 8-K 항목 코드는 사건의 주제를 나타낼 뿐 호재/악재 방향을 의미하지 않는다.\n"
    "- 외국민간발행인(FPI)의 6-K는 국내 기업의 8-K와 제출 주기 및 내용 기준이 달라 "
    "직접 비교할 수 없다.\n"
)


def render_sec_filing_body(
    filing: CompanyFilingRef,
    company: CompanyConfig,
    canonical_url: str,
) -> str:
    period = filing.period_of_report.isoformat() if filing.period_of_report else "해당 없음"
    items_line = (
        f"8-K 항목 코드: {', '.join(filing.items)}"
        if filing.items
        else "8-K 항목 코드: 해당 없음"
    )

    sections = [
        "## 원문",
        "",
        f"{company.name} ({company.ticker}) {filing.form} — "
        f"보고 기준일 {period}, "
        f"제출일 {filing.filing_date.isoformat()}, "
        f"accession {filing.accession_number}",
        "",
        items_line,
        "",
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

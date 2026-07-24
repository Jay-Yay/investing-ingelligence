from __future__ import annotations

from investor_intel.collectors.dart_filings_parser import DartFilingRef

DART_LIMITATIONS_NOTE = (
    "- 이 공시는 특정 시점의 규제 공시이며 투자 자문이 아니다.\n"
    "- 원문 XML은 이 단계에서 수집하지 않으며, 메타데이터와 DART 뷰어 링크만 캡처한다.\n"
    "- 정정보고서가 있을 수 있으며, 이 컬렉터는 최초 접수 건과 정정 건을 동일하게 개별 문서로 "
    "취급한다(자동 병합하지 않음).\n"
)


def render_dart_filing_body(filing: DartFilingRef, canonical_url: str) -> str:
    sections = [
        "## 원문",
        "",
        f"{filing.corp_name} {filing.report_nm} — "
        f"접수일 {filing.rcept_dt.isoformat()}, "
        f"접수번호 {filing.rcept_no}, "
        f"제출인 {filing.flr_nm}",
        "",
        "## 공시 해석 시 유의사항",
        "",
        DART_LIMITATIONS_NOTE,
        "## 핵심 주장",
        "",
        "## 근거",
        "",
        "## 반대 근거",
        "",
        "## 언급 자산",
        "",
        f"{filing.corp_name} {filing.report_nm} 공시.",
        "",
        "## 포트폴리오 관련성",
        "",
        "## 출처",
        "",
        f"- [원문]({canonical_url})",
        "",
    ]
    return "\n".join(sections)

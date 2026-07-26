from __future__ import annotations

from investor_intel.collectors.dart_filings_parser import DartFilingRef

DART_LIMITATIONS_NOTE = (
    "- 이 공시는 특정 시점의 규제 공시이며 투자 자문이 아니다.\n"
    "- 사업보고서/반기보고서/분기보고서는 document.xml 원문에서 텍스트를 추출해 캡처한다(태그만 "
    "제거한 단순 변환이라 표 구조가 완벽히 보존되진 않으며, 최대 4만자까지만 담긴다). 그 외 "
    "공시 유형은 메타데이터와 DART 뷰어 링크만 캡처한다.\n"
    "- 정정보고서가 있을 수 있으며, 이 컬렉터는 최초 접수 건과 정정 건을 동일하게 개별 문서로 "
    "취급한다(자동 병합하지 않음).\n"
)


def render_dart_filing_body(
    filing: DartFilingRef, canonical_url: str, full_text: str | None = None
) -> str:
    body_text = full_text or "(본문 미제공 - 원문 링크 참고)"
    body_note = "(document.xml 원문에서 추출한 전체 텍스트)" if full_text else None

    sections = [
        "## 원문",
        "",
        f"{filing.corp_name} {filing.report_nm} — "
        f"접수일 {filing.rcept_dt.isoformat()}, "
        f"접수번호 {filing.rcept_no}, "
        f"제출인 {filing.flr_nm}",
        *([body_note] if body_note else []),
        "",
        body_text,
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

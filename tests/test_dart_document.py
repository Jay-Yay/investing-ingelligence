from datetime import date

from investor_intel.collectors.dart_document import (
    DART_LIMITATIONS_NOTE,
    render_dart_filing_body,
)
from investor_intel.collectors.dart_filings_parser import DartFilingRef


def _filing() -> DartFilingRef:
    return DartFilingRef(
        rcept_no="20240315000001",
        rcept_dt=date(2024, 3, 15),
        report_nm="사업보고서 (2023.12)",
        corp_name="삼성전자",
        corp_code="00126380",
        flr_nm="삼성전자",
        corp_cls="Y",
    )


def test_render_includes_all_required_sections() -> None:
    body = render_dart_filing_body(
        _filing(), "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240315000001"
    )
    for section in (
        "## 원문",
        "## 공시 해석 시 유의사항",
        "## 핵심 주장",
        "## 근거",
        "## 반대 근거",
        "## 언급 자산",
        "## 포트폴리오 관련성",
        "## 출처",
    ):
        assert section in body

    assert "삼성전자" in body
    assert "20240315000001" in body
    assert "2024-03-15" in body
    assert "사업보고서 (2023.12)" in body
    assert "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240315000001" in body


def test_render_includes_limitations_note_verbatim() -> None:
    body = render_dart_filing_body(_filing(), "https://example.com")
    assert DART_LIMITATIONS_NOTE in body

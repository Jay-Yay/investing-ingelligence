from datetime import date

from investor_intel.collectors.sec_companyfacts import FinancialFact, FinancialStatementSnapshot
from investor_intel.collectors.sec_filings_document import (
    SEC_FILING_LIMITATIONS_NOTE,
    render_sec_filing_body,
)
from investor_intel.collectors.sec_filings_parser import CompanyFilingRef
from investor_intel.models.config import CompanyConfig


def _company(is_foreign_private_issuer: bool = False) -> CompanyConfig:
    return CompanyConfig(
        ticker="BE",
        cik="0001664703",
        name="Bloom Energy",
        filing_types=["10-K", "10-Q", "8-K"],
        is_foreign_private_issuer=is_foreign_private_issuer,
    )


def _filing(
    form: str = "10-Q",
    period_of_report: date | None = date(2024, 3, 31),
    items: list[str] | None = None,
) -> CompanyFilingRef:
    return CompanyFilingRef(
        accession_number="0001664703-24-000010",
        filing_date=date(2024, 5, 1),
        period_of_report=period_of_report,
        form=form,
        primary_document="form.htm",
        primary_doc_description=form,
        items=items or [],
    )


def test_render_includes_all_required_sections() -> None:
    body = render_sec_filing_body(_filing(), _company(), "https://example.com/index.htm")
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

    assert "Bloom Energy" in body
    assert "0001664703-24-000010" in body
    assert "2024-03-31" in body
    assert "https://example.com/index.htm" in body


def test_render_includes_limitations_note_verbatim() -> None:
    body = render_sec_filing_body(_filing(), _company(), "https://example.com")
    assert SEC_FILING_LIMITATIONS_NOTE in body


def test_render_shows_8k_item_codes_when_present() -> None:
    filing = _filing(form="8-K", period_of_report=None, items=["2.02", "9.01"])
    body = render_sec_filing_body(filing, _company(), "https://example.com")
    assert "2.02" in body
    assert "9.01" in body


def test_render_handles_missing_period_of_report() -> None:
    filing = _filing(form="8-K", period_of_report=None)
    body = render_sec_filing_body(filing, _company(), "https://example.com")
    assert "해당 없음" in body


def _fact(val: float) -> FinancialFact:
    return FinancialFact(
        concept="Revenues",
        val=val,
        unit="USD",
        start=date(2024, 1, 1),
        end=date(2024, 3, 31),
        accn="0001664703-24-000010",
        form="10-Q",
        fy=2024,
        fp="Q1",
    )


def test_render_includes_financial_snapshot_section_when_data_present() -> None:
    snapshot = FinancialStatementSnapshot(
        revenue=_fact(100_000_000),
        net_income=_fact(5_000_000),
        total_assets=None,
        total_liabilities=None,
    )
    body = render_sec_filing_body(
        _filing(), _company(), "https://example.com", snapshot=snapshot
    )
    assert "## 재무 데이터 (XBRL)" in body
    assert "100,000,000" in body
    assert "5,000,000" in body


def test_render_omits_financial_snapshot_section_when_all_fields_none() -> None:
    snapshot = FinancialStatementSnapshot(
        revenue=None, net_income=None, total_assets=None, total_liabilities=None
    )
    body = render_sec_filing_body(
        _filing(), _company(), "https://example.com", snapshot=snapshot
    )
    assert "## 재무 데이터 (XBRL)" not in body


def test_render_omits_financial_snapshot_section_when_snapshot_is_none() -> None:
    body = render_sec_filing_body(_filing(), _company(), "https://example.com", snapshot=None)
    assert "## 재무 데이터 (XBRL)" not in body


def test_render_labels_press_release_capture_distinctly_from_transcript() -> None:
    filing = _filing(form="8-K", period_of_report=None, items=["2.02", "9.01"])
    body = render_sec_filing_body(
        filing,
        _company(),
        "https://example.com",
        full_text="2분기 매출 발표 보도자료 본문",
        capture_kind="press_release",
    )
    assert "(첨부 실적발표 보도자료 원문)" in body
    assert "2분기 매출 발표 보도자료 본문" in body


def test_render_labels_transcript_capture_distinctly_from_press_release() -> None:
    filing = _filing(form="8-K", period_of_report=None, items=["2.02", "9.01"])
    body = render_sec_filing_body(
        filing,
        _company(),
        "https://example.com",
        full_text="Operator: welcome to the call",
        capture_kind="transcript",
    )
    assert "(첨부 컨퍼런스콜 녹취록 원문)" in body

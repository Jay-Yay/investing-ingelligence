from datetime import date

from investor_intel.collectors.thirteenf_changes import compute_holding_changes
from investor_intel.collectors.thirteenf_document import (
    THIRTEENF_LIMITATIONS_NOTE,
    render_thirteenf_body,
)
from investor_intel.models.config import InvestorConfig
from investor_intel.models.thirteenf import ThirteenFFiling, ThirteenFHolding, VotingAuthority


def _holding(cusip: str, issuer: str, value: int, shares: int) -> ThirteenFHolding:
    return ThirteenFHolding(
        issuer=issuer,
        title_of_class="COM",
        cusip=cusip,
        value_usd_thousands=value,
        shares_or_principal_amount=shares,
        shares_or_principal_type="SH",
        investment_discretion="SOLE",
        voting_authority=VotingAuthority(sole=shares, shared=0, none=0),
    )


def _investor() -> InvestorConfig:
    return InvestorConfig(
        id="duquesne_family_office",
        name="Stanley Druckenmiller",
        fund_name="Duquesne Family Office LLC",
        cik="0001536411",
    )


def test_render_includes_all_required_sections() -> None:
    filing = ThirteenFFiling(
        investor_id="duquesne_family_office",
        cik="0001536411",
        accession_number="0001536411-24-000007",
        form_type="13F-HR",
        filing_date=date(2024, 5, 15),
        period_of_report=date(2024, 3, 31),
        holdings=[_holding("AAA", "Alpha Co", 1000, 100)],
    )
    changes = compute_holding_changes(None, filing.holdings)
    body = render_thirteenf_body(
        filing, _investor(), changes, "https://www.sec.gov/Archives/edgar/data/1536411/x/x-index.htm"
    )

    for section in (
        "## 원문",
        "## 13F 해석 시 유의사항",
        "## 핵심 주장",
        "## 근거",
        "## 반대 근거",
        "## 언급 자산",
        "## 포트폴리오 관련성",
        "## 출처",
    ):
        assert section in body

    assert "Alpha Co" in body
    assert "0001536411-24-000007" in body
    assert "2024-03-31" in body
    assert "https://www.sec.gov/Archives/edgar/data/1536411/x/x-index.htm" in body


def test_render_includes_limitations_note_verbatim() -> None:
    filing = ThirteenFFiling(
        investor_id="duquesne_family_office",
        cik="0001536411",
        accession_number="0001536411-24-000007",
        form_type="13F-HR",
        filing_date=date(2024, 5, 15),
        period_of_report=date(2024, 3, 31),
        holdings=[],
    )
    body = render_thirteenf_body(filing, _investor(), [], "https://example.com")
    assert THIRTEENF_LIMITATIONS_NOTE in body


def test_render_flags_put_call_positions_distinctly() -> None:
    holding = _holding("AAA", "Alpha Co", 1000, 100)
    holding.put_call = "Call"
    filing = ThirteenFFiling(
        investor_id="duquesne_family_office",
        cik="0001536411",
        accession_number="0001536411-24-000007",
        form_type="13F-HR",
        filing_date=date(2024, 5, 15),
        period_of_report=date(2024, 3, 31),
        holdings=[holding],
    )
    changes = compute_holding_changes(None, filing.holdings)
    body = render_thirteenf_body(filing, _investor(), changes, "https://example.com")
    assert "Call" in body

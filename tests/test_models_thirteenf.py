from datetime import date

from investor_intel.models.thirteenf import (
    HoldingChange,
    HoldingChangeType,
    ThirteenFFiling,
    ThirteenFHolding,
    VotingAuthority,
)


def _make_holding(value: int, shares: int, put_call: str | None = None) -> ThirteenFHolding:
    return ThirteenFHolding(
        issuer="NVIDIA CORP",
        title_of_class="COM",
        cusip="67066G104",
        value_usd=value,
        shares_or_principal_amount=shares,
        shares_or_principal_type="SH",
        put_call=put_call,
        investment_discretion="SOLE",
        voting_authority=VotingAuthority(sole=shares, shared=0, none=0),
    )


def test_holding_defaults() -> None:
    holding = _make_holding(1000, 100)
    assert holding.figi is None
    assert holding.put_call is None
    assert holding.other_manager is None


def test_filing_total_value_sums_holdings() -> None:
    filing = ThirteenFFiling(
        investor_id="duquesne_family_office",
        cik="0001536411",
        accession_number="0001536411-24-000007",
        form_type="13F-HR",
        filing_date=date(2024, 5, 15),
        period_of_report=date(2024, 3, 31),
        holdings=[_make_holding(1000, 100), _make_holding(2000, 200)],
    )
    assert filing.total_value_usd == 3000


def test_holding_change_type_values() -> None:
    assert {t.value for t in HoldingChangeType} == {
        "new",
        "sold_out",
        "increased",
        "decreased",
        "held",
    }


def test_holding_change_construction() -> None:
    change = HoldingChange(
        cusip="67066G104",
        issuer="NVIDIA CORP",
        change_type=HoldingChangeType.INCREASED,
        previous_shares=100,
        current_shares=150,
        shares_change_pct=50.0,
        previous_value_usd=1000,
        current_value_usd=1500,
        value_change_usd=500,
        portfolio_weight_pct=12.5,
    )
    assert change.put_call is None

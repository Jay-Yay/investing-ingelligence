from investor_intel.collectors.thirteenf_changes import (
    compute_holding_changes,
    concentration_ratio,
    top_holdings,
)
from investor_intel.models.thirteenf import HoldingChangeType, ThirteenFHolding, VotingAuthority


def _holding(cusip: str, issuer: str, value: int, shares: int, put_call: str | None = None) -> ThirteenFHolding:
    return ThirteenFHolding(
        issuer=issuer,
        title_of_class="COM",
        cusip=cusip,
        value_usd_thousands=value,
        shares_or_principal_amount=shares,
        shares_or_principal_type="SH",
        put_call=put_call,
        investment_discretion="SOLE",
        voting_authority=VotingAuthority(sole=shares, shared=0, none=0),
    )


def test_new_holding_when_absent_from_previous() -> None:
    current = [_holding("AAA", "Alpha Co", 1000, 100)]
    changes = compute_holding_changes(None, current)
    assert len(changes) == 1
    assert changes[0].change_type == HoldingChangeType.NEW
    assert changes[0].current_shares == 100
    assert changes[0].previous_shares is None
    assert changes[0].portfolio_weight_pct == 100.0


def test_sold_out_when_absent_from_current() -> None:
    previous = [_holding("AAA", "Alpha Co", 1000, 100)]
    changes = compute_holding_changes(previous, [])
    assert len(changes) == 1
    assert changes[0].change_type == HoldingChangeType.SOLD_OUT
    assert changes[0].previous_shares == 100
    assert changes[0].current_shares is None


def test_increased_when_shares_go_up() -> None:
    previous = [_holding("AAA", "Alpha Co", 1000, 100)]
    current = [_holding("AAA", "Alpha Co", 1500, 150)]
    changes = compute_holding_changes(previous, current)
    assert changes[0].change_type == HoldingChangeType.INCREASED
    assert changes[0].shares_change_pct == 50.0
    assert changes[0].value_change_usd_thousands == 500


def test_decreased_when_shares_go_down() -> None:
    previous = [_holding("AAA", "Alpha Co", 1000, 100)]
    current = [_holding("AAA", "Alpha Co", 500, 50)]
    changes = compute_holding_changes(previous, current)
    assert changes[0].change_type == HoldingChangeType.DECREASED
    assert changes[0].shares_change_pct == -50.0


def test_held_when_shares_unchanged() -> None:
    previous = [_holding("AAA", "Alpha Co", 1000, 100)]
    current = [_holding("AAA", "Alpha Co", 1100, 100)]
    changes = compute_holding_changes(previous, current)
    assert changes[0].change_type == HoldingChangeType.HELD
    assert changes[0].shares_change_pct == 0.0


def test_put_call_flag_carried_through() -> None:
    previous = [_holding("AAA", "Alpha Co", 1000, 100, put_call="Call")]
    current = [_holding("AAA", "Alpha Co", 1000, 100, put_call="Call")]
    changes = compute_holding_changes(previous, current)
    assert changes[0].put_call == "Call"


def test_top_holdings_sorted_by_value_desc() -> None:
    holdings = [
        _holding("AAA", "Alpha", 100, 10),
        _holding("BBB", "Beta", 300, 30),
        _holding("CCC", "Gamma", 200, 20),
    ]
    top = top_holdings(holdings, n=2)
    assert [h.cusip for h in top] == ["BBB", "CCC"]


def test_concentration_ratio_top_n() -> None:
    holdings = [
        _holding("AAA", "Alpha", 600, 10),
        _holding("BBB", "Beta", 300, 30),
        _holding("CCC", "Gamma", 100, 20),
    ]
    assert concentration_ratio(holdings, top_n=1) == 60.0
    assert concentration_ratio(holdings, top_n=2) == 90.0


def test_concentration_ratio_empty_holdings_is_zero() -> None:
    assert concentration_ratio([], top_n=5) == 0.0

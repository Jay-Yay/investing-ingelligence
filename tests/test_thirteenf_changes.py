from investor_intel.collectors.thirteenf_changes import (
    aggregate_positions,
    compute_holding_changes,
    concentration_ratio,
    distinct_issuers,
    position_count,
    top_holdings,
)
from investor_intel.models.thirteenf import HoldingChangeType, ThirteenFHolding, VotingAuthority


def _holding(
    cusip: str, issuer: str, value: int, shares: int, put_call: str | None = None
) -> ThirteenFHolding:
    return ThirteenFHolding(
        issuer=issuer,
        title_of_class="COM",
        cusip=cusip,
        value_usd=value,
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
    assert changes[0].value_change_usd == 500


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


# --- 여러 행으로 쪼개 보고된 같은 포지션을 합산하는지 ---------------------------------
# 13F는 같은 종목을 운용 재량·공동 운용사별로 여러 행으로 나눠 보고한다. 예전 구현은
# CUSIP으로 dict를 만들어 마지막 행만 남겼다 - 실측 필링에서 121행이 37종목이었고 표의
# 비중 합계가 21.42%밖에 되지 않았다.


def test_aggregate_positions_sums_rows_sharing_a_cusip() -> None:
    rows = [
        _holding("AAA", "Alpha Co", 600, 60),
        _holding("AAA", "Alpha Co", 300, 30),
        _holding("AAA", "Alpha Co", 100, 10),
    ]
    merged = aggregate_positions(rows)
    assert len(merged) == 1
    holding, row_count = merged[("AAA", None)]
    assert holding.value_usd == 1000
    assert holding.shares_or_principal_amount == 100
    assert row_count == 3


def test_aggregate_positions_keeps_put_call_separate_from_common() -> None:
    """13F 유의사항이 명시한 대로 put/call 포지션은 보통주와 섞지 않는다."""
    rows = [
        _holding("AAA", "Alpha Co", 600, 60),
        _holding("AAA", "Alpha Co", 400, 40, put_call="Put"),
    ]
    merged = aggregate_positions(rows)
    assert set(merged) == {("AAA", None), ("AAA", "Put")}


def test_position_count_counts_positions_not_rows() -> None:
    rows = [
        _holding("AAA", "Alpha Co", 600, 60),
        _holding("AAA", "Alpha Co", 300, 30),
        _holding("BBB", "Beta Co", 100, 10),
    ]
    assert position_count(rows) == 2
    assert len(rows) == 3


def test_changes_report_aggregated_totals_and_row_count() -> None:
    previous = [_holding("AAA", "Alpha Co", 500, 50)]
    current = [
        _holding("AAA", "Alpha Co", 600, 60),
        _holding("AAA", "Alpha Co", 400, 40),
    ]
    (change,) = compute_holding_changes(previous, current)
    assert change.change_type == HoldingChangeType.INCREASED
    assert change.current_value_usd == 1000
    assert change.current_shares == 100
    assert change.row_count == 2


def test_weights_sum_to_100_across_aggregated_positions() -> None:
    """행별로 나눠 계산하면 비중 합계가 100%에 못 미친다 - 회귀 감시용."""
    current = [
        _holding("AAA", "Alpha Co", 600, 60),
        _holding("AAA", "Alpha Co", 400, 40),
        _holding("BBB", "Beta Co", 1000, 100),
    ]
    changes = compute_holding_changes(None, current)
    assert round(sum(c.portfolio_weight_pct or 0 for c in changes), 2) == 100.0


def test_concentration_ratio_uses_aggregated_positions() -> None:
    """상위 5종목 집중도를 행 기준으로 세면 한 종목이 여러 슬롯을 차지한다."""
    holdings = [_holding("AAA", "Alpha Co", 100, 10) for _ in range(6)]
    holdings.append(_holding("BBB", "Beta Co", 400, 40))
    # 포지션은 Alpha(600) / Beta(400) 둘뿐이므로 상위 5종목이 곧 전체다.
    assert concentration_ratio(holdings, top_n=5) == 100.0


def test_distinct_issuers_dedupes_and_orders_by_value() -> None:
    holdings = [
        _holding("AAA", "Alpha Co", 100, 10),
        _holding("BBB", "Beta Co", 900, 90),
        _holding("AAA", "Alpha Co", 200, 20),
    ]
    assert distinct_issuers(holdings) == ["Beta Co", "Alpha Co"]


def test_top_holdings_ranks_by_aggregated_value() -> None:
    """합산 전에는 Beta가 1위로 보이지만, Alpha의 두 행을 합치면 Alpha가 1위다."""
    holdings = [
        _holding("AAA", "Alpha Co", 600, 60),
        _holding("AAA", "Alpha Co", 500, 50),
        _holding("BBB", "Beta Co", 900, 90),
    ]
    assert [h.issuer for h in top_holdings(holdings, n=1)] == ["Alpha Co"]

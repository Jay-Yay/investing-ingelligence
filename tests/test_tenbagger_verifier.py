from datetime import date

from investor_intel.analysis.tenbagger_verifier import verify_tenbagger
from investor_intel.market_data.provider import FundamentalPoint, QuarterlyFundamentals

_DATES = [
    date(2025, 3, 31),
    date(2025, 6, 30),
    date(2025, 9, 30),
    date(2025, 12, 31),
    date(2026, 3, 31),
]


def _points(values: list[float]) -> list[FundamentalPoint]:
    return [FundamentalPoint(as_of_date=d, value=v) for d, v in zip(_DATES, values, strict=True)]


def _fundamentals(**overrides: list[FundamentalPoint]) -> QuarterlyFundamentals:
    defaults: dict[str, list[FundamentalPoint]] = {
        "revenue": _points([100.0, 120.0, 150.0, 200.0, 300.0]),
        "operating_income": _points([-40.0, -36.0, -30.0, -20.0, -15.0]),
        "net_income": _points([-10.0, -8.0, -5.0, 60.0, 82.0]),
        "operating_cash_flow": _points([-20.0, -17.0, -8.0, 83.0, 226.0]),
        "capital_expenditure": _points([-54.0, -51.0, -95.0, -205.0, -247.0]),
        "cash_and_equivalents": [FundamentalPoint(as_of_date=_DATES[-1], value=929.82)],
        "current_assets": [FundamentalPoint(as_of_date=_DATES[-1], value=1200.0)],
        "current_liabilities": [FundamentalPoint(as_of_date=_DATES[-1], value=144.0)],
        "total_debt": [FundamentalPoint(as_of_date=_DATES[-1], value=500.0)],
        "stockholders_equity": [FundamentalPoint(as_of_date=_DATES[-1], value=2318.6)],
    }
    defaults.update(overrides)
    return QuarterlyFundamentals(symbol="NBIS", **defaults)


def test_scenario_required_revenue_and_income_scale_with_target_multiple() -> None:
    result = verify_tenbagger(
        _fundamentals(), market_cap=47_674.0, currency="USD", target_multiple=10.0, years=2.0
    )
    s = result.scenario
    # 배수를 그대로 유지한다는 가정에서는, 필요 매출/순이익도 정확히 target_multiple배가 된다
    assert s.required_revenue is not None and s.ttm_revenue is not None
    assert s.required_revenue == s.ttm_revenue * 10.0
    assert s.required_net_income is not None and s.ttm_net_income is not None
    assert s.required_net_income == s.ttm_net_income * 10.0


def test_required_cagr_matches_closed_form() -> None:
    result = verify_tenbagger(
        _fundamentals(), market_cap=47_674.0, currency="USD", target_multiple=10.0, years=2.0
    )
    # 10배를 2년 안에 달성하려면 10**0.5 - 1 ≈ 216.2%의 연복리 성장이 필요하다
    assert result.scenario.required_cagr_revenue is not None
    assert abs(result.scenario.required_cagr_revenue - (10.0**0.5 - 1)) < 1e-9


def test_growth_acceleration_is_none_with_fewer_than_two_yoy_datapoints() -> None:
    result = verify_tenbagger(_fundamentals(), market_cap=47_674.0, currency="USD")
    # revenue가 5분기뿐이면 YoY 성장률이 1개만 나와 가속/둔화를 비교할 기준이 없다
    assert result.growth_acceleration is None


def test_growth_acceleration_flags_when_latest_yoy_exceeds_previous() -> None:
    extra_dates = [date(2024, 6, 30)] + _DATES
    revenue = [
        FundamentalPoint(as_of_date=d, value=v)
        for d, v in zip(extra_dates, [50.0, 100.0, 120.0, 150.0, 200.0, 300.0], strict=True)
    ]
    result = verify_tenbagger(
        _fundamentals(revenue=revenue), market_cap=47_674.0, currency="USD"
    )
    assert result.growth_acceleration is not None
    # YoY: (200-50)/50=3.0(2025-12), (300-100)/100=2.0(2026-03) -> 최신이 더 낮으므로 둔화
    assert result.growth_acceleration.accelerating is False
    assert result.growth_acceleration.delta < 0


def test_margin_trend_detects_improving_operating_margin() -> None:
    result = verify_tenbagger(_fundamentals(), market_cap=47_674.0, currency="USD")
    assert result.margin_trend is not None
    assert result.margin_trend.trend == "개선"
    assert result.margin_trend.latest_margin == -15.0 / 300.0


def test_survival_verdict_flips_from_healthy_to_unhealthy_once_capex_is_included() -> None:
    """이 테스트는 10x_verifier.py 스탠드얼론 스크립트에서 실제로 났던 버그(OCF만 보고
    "무증자 생존 가능성 높음"이라 오판했던 것)를 회귀 방지한다: TTM OCF는 흑자(284)지만
    CapEx(600)를 반영하면 FCF는 대규모 적자(-316)가 되어야 한다."""
    result = verify_tenbagger(_fundamentals(), market_cap=47_674.0, currency="USD")
    survival = result.survival

    ttm_ocf = -8.0 + 83.0 + 226.0 + -17.0  # 최근 4개 분기 합
    ttm_capex = abs(-95.0 + -205.0 + -247.0 + -51.0)
    assert survival.ttm_operating_cash_flow == ttm_ocf
    assert survival.ttm_operating_cash_flow is not None and survival.ttm_operating_cash_flow > 0
    assert survival.ttm_capital_expenditure == ttm_capex
    assert survival.ttm_free_cash_flow == ttm_ocf - ttm_capex
    assert survival.ttm_free_cash_flow is not None and survival.ttm_free_cash_flow < 0
    assert "FCF 적자" in survival.verdict
    assert survival.runway_quarters is not None


def test_survival_without_capex_data_flags_verdict_as_reference_only() -> None:
    result = verify_tenbagger(
        _fundamentals(capital_expenditure=[]), market_cap=47_674.0, currency="USD"
    )
    assert result.survival.ttm_capital_expenditure is None
    assert "참고용" in result.survival.verdict


def test_current_ratio_and_debt_to_equity_use_latest_balance_sheet_snapshot() -> None:
    result = verify_tenbagger(_fundamentals(), market_cap=47_674.0, currency="USD")
    assert result.survival.current_ratio == 1200.0 / 144.0
    assert result.survival.debt_to_equity == 500.0 / 2318.6

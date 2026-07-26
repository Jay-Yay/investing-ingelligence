from __future__ import annotations

from investor_intel.market_data.provider import FundamentalPoint, QuarterlyFundamentals
from investor_intel.models.analysis import (
    TenbaggerGrowthAcceleration,
    TenbaggerMarginTrend,
    TenbaggerScenario,
    TenbaggerSurvival,
    TenbaggerVerification,
)

_MARGIN_TREND_FLAT_EPSILON = 0.0005


def _ttm(points: list[FundamentalPoint]) -> float | None:
    if not points:
        return None
    n = min(4, len(points))
    return sum(p.value for p in points[-n:])


def _yoy_growth_series(points: list[FundamentalPoint]) -> list[float]:
    """분기별 YoY 성장률. points는 오래된->최신 순으로 정렬돼 있고 분기 간격이 균일하다고
    가정한다(같은 소스에서 나온 분기 재무제표라 실제로 항상 성립) - 5개 미만이면 계산 불가."""
    if len(points) < 5:
        return []
    growths = []
    for i in range(4, len(points)):
        prev, cur = points[i - 4].value, points[i].value
        if prev:
            growths.append((cur - prev) / abs(prev))
    return growths


def _margin_series(
    revenue: list[FundamentalPoint], operating_income: list[FundamentalPoint]
) -> list[float]:
    op_by_date = {p.as_of_date: p.value for p in operating_income}
    margins = []
    for r in revenue:
        op = op_by_date.get(r.as_of_date)
        if op is not None and r.value:
            margins.append(op / r.value)
    return margins


def _linear_slope(values: list[float]) -> float:
    n = len(values)
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    covariance = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    variance = sum((i - mean_x) ** 2 for i in range(n))
    return covariance / variance if variance else 0.0


def _compute_scenario(
    market_cap: float,
    ttm_revenue: float | None,
    ttm_net_income: float | None,
    yoy_growth: list[float],
    target_multiple: float,
    years: float,
    derate_factor: float,
) -> TenbaggerScenario:
    ps_ratio = market_cap / ttm_revenue if ttm_revenue else None
    pe_ratio = market_cap / ttm_net_income if ttm_net_income and ttm_net_income > 0 else None
    target_market_cap = market_cap * target_multiple

    required_revenue = None
    required_net_income = None
    required_cagr_revenue = None
    if ps_ratio:
        future_ps = ps_ratio * derate_factor
        required_revenue = target_market_cap / future_ps if future_ps else None
    if pe_ratio:
        future_pe = pe_ratio * derate_factor
        required_net_income = target_market_cap / future_pe if future_pe else None
    if required_revenue and ttm_revenue:
        ratio = required_revenue / ttm_revenue
        required_cagr_revenue = ratio ** (1 / years) - 1 if ratio > 0 else None

    recent_avg_yoy_growth = sum(yoy_growth) / len(yoy_growth) if yoy_growth else None
    feasible_by_trend = (
        recent_avg_yoy_growth >= required_cagr_revenue
        if recent_avg_yoy_growth is not None and required_cagr_revenue is not None
        else None
    )

    return TenbaggerScenario(
        target_multiple=target_multiple,
        years=years,
        derate_factor=derate_factor,
        market_cap=market_cap,
        ttm_revenue=ttm_revenue,
        ttm_net_income=ttm_net_income,
        ps_ratio=ps_ratio,
        pe_ratio=pe_ratio,
        required_revenue=required_revenue,
        required_net_income=required_net_income,
        required_cagr_revenue=required_cagr_revenue,
        recent_avg_yoy_growth=recent_avg_yoy_growth,
        feasible_by_trend=feasible_by_trend,
    )


def _compute_growth_acceleration(yoy_growth: list[float]) -> TenbaggerGrowthAcceleration | None:
    if len(yoy_growth) < 2:
        return None
    delta = yoy_growth[-1] - yoy_growth[-2]
    return TenbaggerGrowthAcceleration(
        latest_yoy_growth=yoy_growth[-1],
        prev_yoy_growth=yoy_growth[-2],
        accelerating=delta > 0,
        delta=delta,
    )


def _compute_margin_trend(margins: list[float]) -> TenbaggerMarginTrend | None:
    if len(margins) < 2:
        return None
    slope = _linear_slope(margins)
    trend = (
        "개선"
        if slope > _MARGIN_TREND_FLAT_EPSILON
        else ("악화" if slope < -_MARGIN_TREND_FLAT_EPSILON else "횡보")
    )
    mean_margin = sum(margins) / len(margins)
    variance = sum((m - mean_margin) ** 2 for m in margins) / len(margins)
    std_margin = variance**0.5
    return TenbaggerMarginTrend(
        slope_per_quarter=slope,
        trend=trend,
        latest_margin=margins[-1],
        mean_margin=mean_margin,
        std_margin=std_margin,
        warning_threshold_margin=mean_margin - std_margin,
    )


def _compute_survival(
    current_ratio: float | None,
    debt_to_equity: float | None,
    ttm_ocf: float | None,
    ttm_capex: float | None,
    cash: float | None,
) -> TenbaggerSurvival:
    if ttm_ocf is None:
        return TenbaggerSurvival(
            current_ratio=current_ratio,
            debt_to_equity=debt_to_equity,
            ttm_operating_cash_flow=None,
            ttm_capital_expenditure=None,
            ttm_free_cash_flow=None,
            cash=cash,
            runway_quarters=None,
            verdict="영업활동현금흐름 데이터 없음 - 판정 불가",
        )

    if ttm_capex is None:
        verdict = (
            "OCF 흑자 (⚠️ CapEx 데이터 미확보 - 자본지출 미반영 판정, 참고용)"
            if ttm_ocf >= 0
            else "OCF 적자 (CapEx 데이터도 없어 실제 상황은 더 나쁠 가능성)"
        )
        return TenbaggerSurvival(
            current_ratio=current_ratio,
            debt_to_equity=debt_to_equity,
            ttm_operating_cash_flow=ttm_ocf,
            ttm_capital_expenditure=None,
            ttm_free_cash_flow=None,
            cash=cash,
            runway_quarters=None,
            verdict=verdict,
        )

    capex_outflow = abs(ttm_capex)  # Yahoo는 보통 음수(유출)로 보고하므로 지출 규모로 정규화
    fcf = ttm_ocf - capex_outflow
    runway_quarters = None
    if fcf >= 0:
        verdict = "CapEx 반영 후에도 잉여현금흐름 흑자 → 무증자 생존 가능성 높음"
    else:
        if cash:
            quarterly_burn = abs(fcf) / 4
            runway_quarters = cash / quarterly_burn if quarterly_burn else None
        verdict = (
            f"OCF는 흑자여도 CapEx 반영 시 FCF 적자 → 사실상 무증자 생존 어려움, "
            f"현재 현금 기준 약 {runway_quarters:.1f}분기치 러웨이"
            if runway_quarters is not None
            else "FCF 적자, 현금 데이터 부족 → 러웨이 산정 불가, 추가 자금조달 의존 가능성 높음"
        )

    return TenbaggerSurvival(
        current_ratio=current_ratio,
        debt_to_equity=debt_to_equity,
        ttm_operating_cash_flow=ttm_ocf,
        ttm_capital_expenditure=capex_outflow,
        ttm_free_cash_flow=fcf,
        cash=cash,
        runway_quarters=runway_quarters,
        verdict=verdict,
    )


def verify_tenbagger(
    fundamentals: QuarterlyFundamentals,
    market_cap: float,
    currency: str,
    target_multiple: float = 10.0,
    years: float = 2.0,
    derate_factor: float = 1.0,
) -> TenbaggerVerification:
    """10x_verifier 스크립트의 정량 계산 로직 이식. Q1(필요 매출/이익), Q2(필요 CAGR vs 최근
    실제 성장률), Q3 프록시(매출 성장 가속 여부), Q7(마진 추세), Q9(CapEx 반영 FCF 기준 무증자
    생존 가능성), Q10 프록시(마진 조기경보 임계치)를 계산한다.

    Q4/Q5/Q6/Q8/Q10 서술처럼 정성적 판단이 필요한 질문은 이 함수의 범위 밖이다.
    """
    ttm_revenue = _ttm(fundamentals.revenue)
    ttm_net_income = _ttm(fundamentals.net_income)
    ttm_ocf = _ttm(fundamentals.operating_cash_flow)
    ttm_capex = _ttm(fundamentals.capital_expenditure)

    yoy_growth = _yoy_growth_series(fundamentals.revenue)
    margins = _margin_series(fundamentals.revenue, fundamentals.operating_income)

    scenario = _compute_scenario(
        market_cap, ttm_revenue, ttm_net_income, yoy_growth, target_multiple, years, derate_factor
    )

    current_ratio = None
    if fundamentals.current_assets and fundamentals.current_liabilities:
        latest_cl = fundamentals.current_liabilities[-1].value
        current_ratio = fundamentals.current_assets[-1].value / latest_cl if latest_cl else None

    debt_to_equity = None
    if fundamentals.total_debt and fundamentals.stockholders_equity:
        latest_debt = fundamentals.total_debt[-1].value
        latest_equity = fundamentals.stockholders_equity[-1].value
        debt_to_equity = latest_debt / latest_equity if latest_equity else None

    cash = (
        fundamentals.cash_and_equivalents[-1].value
        if fundamentals.cash_and_equivalents
        else None
    )

    survival = _compute_survival(current_ratio, debt_to_equity, ttm_ocf, ttm_capex, cash)

    return TenbaggerVerification(
        symbol=fundamentals.symbol,
        currency=currency,
        scenario=scenario,
        growth_acceleration=_compute_growth_acceleration(yoy_growth),
        margin_trend=_compute_margin_trend(margins),
        survival=survival,
    )

from datetime import UTC, date, datetime

from investor_intel.models.config import (
    ConfidenceConfig,
    HardGateDefinition,
    HysteresisConfig,
    MetricSpec,
)
from investor_intel.scoring.earnings_revision import EarningsRevisionInputs
from investor_intel.scoring.models import FactType, Feature, SourceTier, ThesisStatus, TradeSignal
from investor_intel.scoring.pipeline import (
    StockScoringInputs,
    compute_stock_score,
    new_buy_signal_allowed,
    reduce_or_sell_review_triggered,
)
from investor_intel.scoring.price_supply_demand import PriceSupplyDemandMetrics

_AS_OF = date(2026, 8, 2)
_METRIC_SPECS = {
    "metric_a": MetricSpec(kind="growth_rate_pct", bad=-10, good=10),
}
_HYSTERESIS = HysteresisConfig(
    entry_new_buy=72, maintain_buy=62, reduce_review=55, sell_review=45, cooldown_trading_days=5
)
_CONFIDENCE = ConfidenceConfig()
_PRICE_METRICS = PriceSupplyDemandMetrics(
    as_of=_AS_OF, close=100.0, ma20=95.0, ma60=90.0, ma120=85.0, ma200=80.0, ma20_slope_5d=1.0,
    pct_below_52w_high=-5.0, return_5d=1.0, return_20d=5.0, rs_20d_vs_benchmark=3.0,
    rs_60d_vs_benchmark=5.0, volume_change_ratio_20d=1.1, volatility_20d_pct=2.0,
    max_drawdown_1y_pct=-10.0,
)


def _feature(metric: str, value: float) -> Feature:
    return Feature(
        ticker="X",
        metric=metric,
        value=value,
        unit="pct",
        period="2026Q2",
        published_at=datetime(2026, 7, 30, tzinfo=UTC),
        retrieved_at=datetime(2026, 8, 2, tzinfo=UTC),
        source_name="test",
        source_url="https://example.com",
        source_tier=SourceTier.BROKER,
        fact_type=FactType.ESTIMATE,
        confidence=0.8,
        max_age_days=90,
    )


def _base_inputs(**overrides) -> StockScoringInputs:
    defaults = dict(
        ticker="X",
        as_of=_AS_OF,
        model_version="1.0.0",
        category_weights={"cat_a": 100.0},
        metric_categories={"cat_a": ["metric_a"]},
        metric_specs=_METRIC_SPECS,
        features=[_feature("metric_a", 10.0)],
        hysteresis_config=_HYSTERESIS,
        confidence_config=_CONFIDENCE,
        currently_held=False,
        days_since_last_change=999,
    )
    defaults.update(overrides)
    return StockScoringInputs(**defaults)


def test_same_input_yields_same_output_deterministic() -> None:
    inputs = _base_inputs()
    r1, h1 = compute_stock_score(inputs)
    r2, h2 = compute_stock_score(inputs)
    assert r1.total_score == r2.total_score
    assert r1.confidence == r2.confidence
    assert h1.signal == h2.signal


def test_full_category_coverage_yields_max_score() -> None:
    inputs = _base_inputs()
    result, _ = compute_stock_score(inputs)
    assert result.total_score == 100.0


def test_missing_data_produces_missing_critical_entries() -> None:
    inputs = _base_inputs(features=[])
    result, _ = compute_stock_score(inputs)
    assert result.total_score is None
    assert "metric_a" in result.missing_critical_data


def test_hard_gate_blocks_buy_signal_even_with_perfect_score() -> None:
    gates = [HardGateDefinition(id="gate_a", description="test gate")]
    inputs = _base_inputs(hard_gate_definitions=gates, triggered_gate_ids={"gate_a"})
    result, hysteresis = compute_stock_score(inputs)
    assert result.total_score == 100.0
    buy_signals = (TradeSignal.STRONG_BUY_CANDIDATE, TradeSignal.ACCUMULATE_CANDIDATE)
    assert hysteresis.signal not in buy_signals
    assert any(h.triggered for h in result.hard_gates)
    assert result.thesis_status == ThesisStatus.IMPAIRED


def test_new_buy_signal_allowed_requires_all_conditions() -> None:
    inputs = _base_inputs()
    result, _ = compute_stock_score(inputs)
    allowed = new_buy_signal_allowed(
        result,
        min_confidence=0.0,
        min_total_score=70.0,
        consecutive_score_increases=2,
        min_consecutive_increases_required=2,
        secondary_confirmations_met=2,
        min_secondary_confirmations_required=2,
    )
    assert allowed is True

    blocked_by_confirmations = new_buy_signal_allowed(
        result,
        min_confidence=0.0,
        min_total_score=70.0,
        consecutive_score_increases=2,
        min_consecutive_increases_required=2,
        secondary_confirmations_met=0,
        min_secondary_confirmations_required=2,
    )
    assert blocked_by_confirmations is False


def test_new_buy_signal_blocked_when_hard_gate_triggered() -> None:
    gates = [HardGateDefinition(id="gate_a", description="test gate")]
    inputs = _base_inputs(hard_gate_definitions=gates, triggered_gate_ids={"gate_a"})
    result, _ = compute_stock_score(inputs)
    allowed = new_buy_signal_allowed(
        result, min_confidence=0.0, min_total_score=0.0, consecutive_score_increases=5,
        min_consecutive_increases_required=1, secondary_confirmations_met=5,
        min_secondary_confirmations_required=1,
    )
    assert allowed is False


def test_reduce_or_sell_review_triggered_on_low_score() -> None:
    inputs = _base_inputs(features=[_feature("metric_a", -10.0)])  # -> score 0
    result, _ = compute_stock_score(inputs)
    assert reduce_or_sell_review_triggered(result, consecutive_eps_cut_quarters=0) is True


def test_reduce_or_sell_review_triggered_on_eps_cut_streak() -> None:
    inputs = _base_inputs()  # score 100, otherwise no review trigger
    result, _ = compute_stock_score(inputs)
    assert reduce_or_sell_review_triggered(result, consecutive_eps_cut_quarters=2) is True
    assert reduce_or_sell_review_triggered(result, consecutive_eps_cut_quarters=0) is False


def test_valuation_and_price_and_macro_categories_integrate_via_dedicated_modules() -> None:
    from investor_intel.scoring.valuation_scenarios import build_case, build_valuation_scenarios

    bear = build_case(10.0, "normalized_midcycle_earnings", 5.0, "a", "i")
    base = build_case(15.0, "current_forward_earnings", 7.0, "a", "i")
    bull = build_case(20.0, "peak_earnings", 9.0, "a", "i")
    scenarios = build_valuation_scenarios("X", "USD", bear, base, bull)

    inputs = _base_inputs(
        category_weights={
            "cat_a": 40.0,
            "earnings_outlook": 20.0,
            "normalized_valuation": 20.0,
            "price_supply_demand": 10.0,
            "macro_liquidity": 10.0,
        },
        earnings_revision_inputs=EarningsRevisionInputs(ticker="X", eps_revision_1m_pct=5.0),
        valuation_scenarios=scenarios,
        current_price=base.fair_value,
        price_metrics=_PRICE_METRICS,
        macro_liquidity_score=70.0,
    )
    result, _ = compute_stock_score(inputs)
    categories = {c.category: c.score for c in result.category_scores}
    assert categories["normalized_valuation"] == 50.0  # current_price == base fair value
    assert categories["macro_liquidity"] == 70.0
    assert categories["price_supply_demand"] is not None
    assert categories["earnings_outlook"] is not None

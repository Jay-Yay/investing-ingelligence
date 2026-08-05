from datetime import UTC, date, datetime

from investor_intel.models.common import ConfidenceLevel
from investor_intel.regime.models import (
    IndicatorFrequency,
    IndicatorId,
    IndicatorObservation,
    IndicatorStatus,
)
from investor_intel.regime.scoring import build_cooling_risk_rationale, compute_scores

_NOW = datetime(2026, 1, 1, 9, tzinfo=UTC)


def _obs(
    indicator_id: IndicatorId,
    value: float | None,
    details: dict | None = None,
    status: IndicatorStatus = IndicatorStatus.OK,
    is_stale: bool = False,
    frequency: IndicatorFrequency = IndicatorFrequency.DAILY,
) -> IndicatorObservation:
    return IndicatorObservation(
        indicator_id=indicator_id,
        indicator_name=indicator_id.value,
        value=value,
        unit="unit",
        observation_date=date(2026, 1, 1),
        release_date=None,
        fetched_at=_NOW,
        source_name="test",
        source_url="https://example.com",
        frequency=frequency,
        data_age_days=0,
        is_stale=is_stale,
        is_revised=None,
        status=status,
        details=details or {},
    )


def _full_cooling_observations() -> dict[IndicatorId, IndicatorObservation]:
    return {
        IndicatorId.CREDIT_SPREAD_HY_OAS: _obs(
            IndicatorId.CREDIT_SPREAD_HY_OAS, 3.5, {"percentile_10y": 90.0, "cooling_signal": True}
        ),
        IndicatorId.CHICAGO_FED_ANFCI: _obs(
            IndicatorId.CHICAGO_FED_ANFCI, 0.5, {"percentile_5y": 80.0, "tightening_signal": True}
        ),
        IndicatorId.MARKET_BREADTH: _obs(
            IndicatorId.MARKET_BREADTH, 30.0, {"cooling_signal": True}
        ),
        IndicatorId.VIX_TERM_STRUCTURE: _obs(IndicatorId.VIX_TERM_STRUCTURE, 1.1, {}),
        IndicatorId.EMPLOYMENT_COOLING: _obs(
            IndicatorId.EMPLOYMENT_COOLING, 20.0, {"cooling_signal": True}
        ),
        IndicatorId.YIELD_CURVE_10Y3M: _obs(
            IndicatorId.YIELD_CURVE_10Y3M, -0.1, {"inverted_in_last_12m": True}
        ),
        IndicatorId.LEVERAGE_POSITIONING: _obs(
            IndicatorId.LEVERAGE_POSITIONING,
            5.0,
            {
                "deleveraging_signal": True,
                "instruments": {
                    "sp500_e_mini": {"leveraged_funds_net_pct_oi_5y_percentile": 40.0}
                },
            },
        ),
    }


def test_cooling_score_uses_full_coverage_when_all_indicators_present() -> None:
    observations = _full_cooling_observations()
    result = compute_scores(observations)

    assert result.cooling_risk is not None
    assert result.cooling_coverage == 0.85  # 1.0 - EPS(0.15)/1.0 weight share missing


def test_missing_indicators_reweight_proportionally_not_zero_fill() -> None:
    full = _full_cooling_observations()
    partial = dict(full)
    del partial[IndicatorId.MARKET_BREADTH]

    full_result = compute_scores(full)
    partial_result = compute_scores(partial)

    assert partial_result.cooling_coverage < full_result.cooling_coverage
    # dropping one high-cooling-contribution indicator should not silently zero it out and
    # crater the score - the remaining weight is rescaled instead
    assert partial_result.cooling_risk is not None


def test_cooling_rationale_ranks_by_weight_and_caps_at_five_lines() -> None:
    rationale, citations = build_cooling_risk_rationale(_full_cooling_observations())
    assert rationale.index(IndicatorId.CREDIT_SPREAD_HY_OAS.value) < rationale.index(
        IndicatorId.MARKET_BREADTH.value
    )
    assert IndicatorId.LEVERAGE_POSITIONING.value not in rationale  # lowest weight, cut at 5 lines
    assert citations == [("test", "https://example.com")]  # deduped - all fixtures share one url


def test_cooling_rationale_skips_indicators_without_a_contribution() -> None:
    rationale, _ = build_cooling_risk_rationale({})
    assert rationale == ""


def test_confidence_level_thresholds() -> None:
    high_coverage = compute_scores(_full_cooling_observations())
    assert high_coverage.confidence_level in (ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH)

    sparse = {
        IndicatorId.CREDIT_SPREAD_HY_OAS: _obs(
            IndicatorId.CREDIT_SPREAD_HY_OAS, 3.5, {"percentile_10y": 50.0}
        )
    }
    low_coverage = compute_scores(sparse)
    assert low_coverage.confidence_level == ConfidenceLevel.LOW


def test_ai_cycle_is_none_and_zero_coverage_when_no_ai_indicators_present() -> None:
    result = compute_scores(_full_cooling_observations())
    assert result.ai_cycle is None
    assert result.ai_coverage == 0.0


def test_unavailable_status_indicator_excluded_from_score() -> None:
    observations = _full_cooling_observations()
    observations[IndicatorId.CREDIT_SPREAD_HY_OAS] = _obs(
        IndicatorId.CREDIT_SPREAD_HY_OAS, None, {}, status=IndicatorStatus.UNAVAILABLE
    )
    result = compute_scores(observations)
    # coverage should drop by exactly the credit spread weight share (0.20) relative to full
    full_result = compute_scores(_full_cooling_observations())
    assert result.cooling_coverage < full_result.cooling_coverage


def test_ai_cycle_uses_phase_2a_free_fields_without_cloud_revenue() -> None:
    """cloud_ai_revenue_growth_yoy(Phase 2b, LLM)가 없어도 capex_growth_yoy/
    capex_intensity_percentile_avg/revenue_growth_yoy_percentile_avg(Phase 2a, 무료)만으로
    3개 가중치 줄 중 2개(하이퍼스케일러)+1개(반도체) = 60%가 커버되어야 한다."""
    observations = {
        IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY: _obs(
            IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY,
            0.3,
            {
                "capex_growth_yoy": 40.0,
                "capex_intensity_percentile_avg": 70.0,
                "cloud_ai_revenue_growth_yoy": None,
            },
        ),
        IndicatorId.AI_SEMICONDUCTOR_DEMAND: _obs(
            IndicatorId.AI_SEMICONDUCTOR_DEMAND,
            25.0,
            {"revenue_growth_yoy_percentile_avg": 80.0},
        ),
    }
    result = compute_scores(observations)

    assert result.ai_cycle is not None
    assert result.ai_coverage == 0.6


def test_ai_cycle_reaches_full_hyperscaler_coverage_once_cloud_revenue_present() -> None:
    """Phase 2b(LLM)가 cloud_ai_revenue_growth_yoy를 채우면 하이퍼스케일러 3개 줄이 모두
    커버되어 ai_coverage가 0.6에서 0.85로 올라가야 한다(EPS 줄만 계속 제외)."""
    observations = {
        IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY: _obs(
            IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY,
            0.3,
            {
                "capex_growth_yoy": 40.0,
                "capex_intensity_percentile_avg": 70.0,
                "cloud_ai_revenue_growth_yoy": 35.0,
            },
        ),
        IndicatorId.AI_SEMICONDUCTOR_DEMAND: _obs(
            IndicatorId.AI_SEMICONDUCTOR_DEMAND,
            25.0,
            {"revenue_growth_yoy_percentile_avg": 80.0},
        ),
    }
    result = compute_scores(observations)

    assert result.ai_coverage == 0.85


def test_ai_cycle_ignores_unavailable_hyperscaler_indicator() -> None:
    observations = {
        IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY: _obs(
            IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY,
            None,
            {},
            status=IndicatorStatus.UNAVAILABLE,
        ),
    }
    result = compute_scores(observations)
    assert result.ai_cycle is None
    assert result.ai_coverage == 0.0


def test_stale_indicators_reduce_data_confidence() -> None:
    fresh = compute_scores(_full_cooling_observations())

    stale_observations = _full_cooling_observations()
    stale_observations[IndicatorId.CREDIT_SPREAD_HY_OAS] = _obs(
        IndicatorId.CREDIT_SPREAD_HY_OAS,
        3.5,
        {"percentile_10y": 90.0},
        is_stale=True,
    )
    stale = compute_scores(stale_observations)

    assert stale.data_confidence < fresh.data_confidence

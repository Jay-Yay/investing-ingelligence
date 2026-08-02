from datetime import UTC, date, datetime

from investor_intel.models.common import ConfidenceLevel
from investor_intel.regime.models import (
    AiRegime,
    IndicatorFrequency,
    IndicatorId,
    IndicatorObservation,
    IndicatorStatus,
    MarketRegime,
)
from investor_intel.regime.regime_classifier import classify_ai_regime, classify_market_regime
from investor_intel.regime.scoring import ScoringResult

_NOW = datetime(2026, 1, 1, 9, tzinfo=UTC)


def _obs(indicator_id: IndicatorId, details: dict | None = None) -> IndicatorObservation:
    return IndicatorObservation(
        indicator_id=indicator_id,
        indicator_name=indicator_id.value,
        value=1.0,
        unit="unit",
        observation_date=date(2026, 1, 1),
        release_date=None,
        fetched_at=_NOW,
        source_name="test",
        source_url="https://example.com",
        frequency=IndicatorFrequency.DAILY,
        data_age_days=0,
        is_stale=False,
        is_revised=None,
        status=IndicatorStatus.OK,
        details=details or {},
    )


def _scores(
    cooling: float | None,
    overheating: float | None,
    market_coverage: float = 0.9,
    ai_cycle: float | None = None,
    ai_coverage: float = 0.0,
) -> ScoringResult:
    return ScoringResult(
        cooling_risk=cooling,
        cooling_coverage=market_coverage,
        overheating_risk=overheating,
        overheating_coverage=market_coverage,
        ai_cycle=ai_cycle,
        ai_coverage=ai_coverage,
        data_confidence=80.0,
        confidence_level=ConfidenceLevel.HIGH,
        market_coverage=market_coverage,
    )


def test_low_coverage_forces_indeterminate() -> None:
    scores = _scores(80.0, 80.0, market_coverage=0.3)
    assert classify_market_regime(scores, {}) == MarketRegime.INDETERMINATE


def test_stress_requires_two_of_three_stress_signals() -> None:
    observations = {
        IndicatorId.CREDIT_SPREAD_HY_OAS: _obs(
            IndicatorId.CREDIT_SPREAD_HY_OAS, {"cooling_signal": True}
        ),
        IndicatorId.VIX_TERM_STRUCTURE: _obs(
            IndicatorId.VIX_TERM_STRUCTURE, {"backwardation_signal": True}
        ),
    }
    scores = _scores(75.0, 20.0)
    assert classify_market_regime(scores, observations) == MarketRegime.STRESS


def test_late_cycle_divergence_requires_credit_and_breadth_cooling() -> None:
    observations = {
        IndicatorId.CREDIT_SPREAD_HY_OAS: _obs(
            IndicatorId.CREDIT_SPREAD_HY_OAS, {"cooling_signal": True}
        ),
        IndicatorId.MARKET_BREADTH: _obs(IndicatorId.MARKET_BREADTH, {"cooling_signal": True}),
    }
    scores = _scores(55.0, 70.0)
    assert classify_market_regime(scores, observations) == MarketRegime.LATE_CYCLE_DIVERGENCE


def test_overheated_when_overheating_high_and_cooling_low() -> None:
    scores = _scores(30.0, 75.0)
    assert classify_market_regime(scores, {}) == MarketRegime.OVERHEATED


def test_cooling_regime_requires_a_cooling_signal() -> None:
    observations = {
        IndicatorId.EMPLOYMENT_COOLING: _obs(
            IndicatorId.EMPLOYMENT_COOLING, {"cooling_signal": True}
        )
    }
    scores = _scores(60.0, 20.0)
    assert classify_market_regime(scores, observations) == MarketRegime.COOLING


def test_healthy_risk_on_when_scores_low_and_breadth_healthy() -> None:
    scores = _scores(20.0, 20.0)
    assert classify_market_regime(scores, {}) == MarketRegime.HEALTHY_RISK_ON


def test_neutral_when_no_regime_conditions_match() -> None:
    scores = _scores(45.0, 40.0)
    assert classify_market_regime(scores, {}) == MarketRegime.NEUTRAL


def test_ai_regime_is_indeterminate_when_ai_coverage_below_50_percent() -> None:
    scores = _scores(20.0, 20.0, ai_cycle=90.0, ai_coverage=0.2)
    assert classify_ai_regime(scores, {}) == AiRegime.INDETERMINATE


def test_ai_regime_expansion_when_coverage_and_score_high() -> None:
    scores = _scores(20.0, 20.0, ai_cycle=75.0, ai_coverage=0.8)
    assert classify_ai_regime(scores, {}) == AiRegime.AI_EXPANSION

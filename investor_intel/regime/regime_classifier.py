from __future__ import annotations

from investor_intel.regime.models import (
    AiRegime,
    IndicatorId,
    IndicatorObservation,
    IndicatorStatus,
    MarketRegime,
)
from investor_intel.regime.scoring import ScoringResult

_INDETERMINATE_COVERAGE_THRESHOLD = 0.50


def _signal(
    observations: dict[IndicatorId, IndicatorObservation], indicator_id: IndicatorId, key: str
) -> bool:
    obs = observations.get(indicator_id)
    if obs is None or obs.status != IndicatorStatus.OK:
        return False
    return bool(obs.details.get(key))


def classify_market_regime(
    scores: ScoringResult, observations: dict[IndicatorId, IndicatorObservation]
) -> MarketRegime:
    """스펙의 시장 국면 판정 규칙(우선순위: STRESS > LATE_CYCLE_DIVERGENCE > OVERHEATED >
    COOLING > HEALTHY_RISK_ON > NEUTRAL, 데이터 부족 시 INDETERMINATE가 최우선)."""
    if (
        scores.market_coverage < _INDETERMINATE_COVERAGE_THRESHOLD
        or scores.cooling_risk is None
        or scores.overheating_risk is None
    ):
        return MarketRegime.INDETERMINATE

    credit_cooling = _signal(observations, IndicatorId.CREDIT_SPREAD_HY_OAS, "cooling_signal")
    breadth_cooling = _signal(observations, IndicatorId.MARKET_BREADTH, "cooling_signal")
    employment_cooling = _signal(observations, IndicatorId.EMPLOYMENT_COOLING, "cooling_signal")
    vix_backwardation = _signal(
        observations, IndicatorId.VIX_TERM_STRUCTURE, "backwardation_signal"
    )

    stress_count = sum([credit_cooling, vix_backwardation, breadth_cooling])
    if scores.cooling_risk >= 70 and stress_count >= 2:
        return MarketRegime.STRESS

    # 스펙은 "신용/실적(EPS)/시장폭 중 2개 이상 악화"를 요구하지만 EPS 수정 폭은 Phase 1에
    # unavailable이라 가용한 2개(신용/시장폭) 모두 악화인 경우로 대체한다. EPS가 Phase 2에서
    # 채워지면 3개 중 2개 기준으로 완화해야 한다.
    divergence_count = sum([credit_cooling, breadth_cooling])
    if scores.overheating_risk >= 65 and scores.cooling_risk >= 50 and divergence_count >= 2:
        return MarketRegime.LATE_CYCLE_DIVERGENCE

    if scores.overheating_risk >= 70 and scores.cooling_risk < 55:
        return MarketRegime.OVERHEATED

    if 55 <= scores.cooling_risk <= 69 and (credit_cooling or employment_cooling):
        return MarketRegime.COOLING

    if scores.cooling_risk < 40 and scores.overheating_risk < 65 and not breadth_cooling:
        return MarketRegime.HEALTHY_RISK_ON

    return MarketRegime.NEUTRAL


def classify_ai_regime(
    scores: ScoringResult, observations: dict[IndicatorId, IndicatorObservation]
) -> AiRegime:
    """Phase 1에는 monetization_gap을 계산할 지표(하이퍼스케일러 Capex/매출, 반도체 수요)가
    전혀 없어 ai_coverage가 항상 0이므로 이 함수는 사실상 항상 INDETERMINATE를 반환한다 -
    Phase 2에서 ai_hyperscaler_capex_efficiency/ai_semiconductor_demand가 구현되면
    AI_EXPANSION/AI_OVERINVESTMENT_RISK 분기가 실제로 도달 가능해진다."""
    del observations  # Phase 2에서 monetization_gap 계산에 사용 예정
    if scores.ai_coverage < _INDETERMINATE_COVERAGE_THRESHOLD or scores.ai_cycle is None:
        return AiRegime.INDETERMINATE
    if scores.ai_cycle >= 70:
        return AiRegime.AI_EXPANSION
    return AiRegime.NEUTRAL

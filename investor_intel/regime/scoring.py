from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from investor_intel.models.common import ConfidenceLevel
from investor_intel.regime.models import IndicatorId, IndicatorObservation, IndicatorStatus

# (indicator_id, weight) 목록 - 승인된 스펙의 가중치 표를 그대로 옮긴 것. 같은 indicator_id가
# 한 점수 안에 여러 줄로 나올 수 있다(예: ai_cycle_score의 하이퍼스케일러 관련 3개 세부
# 가중치가 전부 ai_hyperscaler_capex_efficiency 지표 하나에서 나옴 - Phase 2에서 그 지표가
# 매출성장/Capex증가/투자효율 세부 수치를 details에 담게 되면 각 줄이 details의 서로 다른
# 키를 참조하도록 _ai_cycle_contribution을 확장한다).
COOLING_RISK_WEIGHTS: list[tuple[IndicatorId, float]] = [
    (IndicatorId.CREDIT_SPREAD_HY_OAS, 0.20),
    (IndicatorId.CHICAGO_FED_ANFCI, 0.15),
    (IndicatorId.EPS_REVISION_BREADTH, 0.15),
    (IndicatorId.MARKET_BREADTH, 0.15),
    (IndicatorId.VIX_TERM_STRUCTURE, 0.10),
    (IndicatorId.EMPLOYMENT_COOLING, 0.10),
    (IndicatorId.YIELD_CURVE_10Y3M, 0.10),
    (IndicatorId.LEVERAGE_POSITIONING, 0.05),
]

OVERHEATING_RISK_WEIGHTS: list[tuple[IndicatorId, float]] = [
    (IndicatorId.LEVERAGE_POSITIONING, 0.25),
    (IndicatorId.MARKET_BREADTH, 0.20),
    (IndicatorId.VIX_TERM_STRUCTURE, 0.15),
    (IndicatorId.CREDIT_SPREAD_HY_OAS, 0.10),
    (IndicatorId.EPS_REVISION_BREADTH, 0.10),
    (IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY, 0.20),
]

AI_CYCLE_WEIGHTS: list[tuple[IndicatorId, float]] = [
    (IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY, 0.25),  # 하이퍼스케일러 AI 매출 성장
    (IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY, 0.15),  # 하이퍼스케일러 Capex 증가
    (IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY, 0.20),  # Capex 투자 효율
    (IndicatorId.AI_SEMICONDUCTOR_DEMAND, 0.25),  # AI 반도체 실수요
    (IndicatorId.EPS_REVISION_BREADTH, 0.15),  # AI 관련 실적 추정치 변화
]

_LOW_CONFIDENCE_COVERAGE_THRESHOLD = 0.70
_HIGH_CONFIDENCE_COVERAGE_THRESHOLD = 0.90
_STALE_PENALTY_PER_INDICATOR = 10.0


def _cooling_contribution(obs: IndicatorObservation) -> float | None:
    """지표별 냉각위험 기여도(0~100, 높을수록 냉각 위험). 스펙이 지표마다 명시한 냉각/과열
    신호 정의를 그대로 코드화한 것 - 일반화된 공식이 아니라 지표별 규칙이다."""
    if obs.status != IndicatorStatus.OK or obs.value is None:
        return None
    d = obs.details
    if obs.indicator_id == IndicatorId.CREDIT_SPREAD_HY_OAS:
        pct = d.get("percentile_10y")
        base = 0.0 if pct is None else float(pct)
        if d.get("cooling_signal"):
            base = max(base, 80.0)
        return min(100.0, base)
    if obs.indicator_id == IndicatorId.CHICAGO_FED_ANFCI:
        pct = d.get("percentile_5y")
        base = 0.0 if pct is None else float(pct)
        if d.get("tightening_signal"):
            base = max(base, 75.0)
        if d.get("easing_signal"):
            base = min(base, 25.0)
        return min(100.0, max(0.0, base))
    if obs.indicator_id == IndicatorId.YIELD_CURVE_10Y3M:
        if d.get("rapid_normalization_signal"):
            return 80.0
        return 20.0 if d.get("inverted_in_last_12m") else 10.0
    if obs.indicator_id == IndicatorId.EMPLOYMENT_COOLING:
        if d.get("cooling_signal"):
            return 90.0
        return 60.0 if d.get("sahm_approaching_signal") else 15.0
    if obs.indicator_id == IndicatorId.VIX_TERM_STRUCTURE:
        ratio = float(obs.value)
        return min(100.0, max(0.0, (ratio - 0.7) / (1.3 - 0.7) * 100.0))
    if obs.indicator_id == IndicatorId.MARKET_BREADTH:
        return min(100.0, max(0.0, 100.0 - float(obs.value)))
    if obs.indicator_id == IndicatorId.LEVERAGE_POSITIONING:
        return 70.0 if d.get("deleveraging_signal") else 15.0
    return None


def _overheating_contribution(obs: IndicatorObservation) -> float | None:
    """지표별 과열위험 기여도(0~100, 높을수록 과열/쏠림/안도감 위험)."""
    if obs.status != IndicatorStatus.OK or obs.value is None:
        return None
    d = obs.details
    if obs.indicator_id == IndicatorId.LEVERAGE_POSITIONING:
        instruments = d.get("instruments") or {}
        pcts: list[float] = []
        for v in instruments.values():
            if not isinstance(v, dict):
                continue
            pct = v.get("leveraged_funds_net_pct_oi_5y_percentile")
            if pct is not None:
                pcts.append(float(pct))
        return None if not pcts else sum(pcts) / len(pcts)
    if obs.indicator_id == IndicatorId.MARKET_BREADTH:
        return 80.0 if d.get("narrow_leadership_signal") else 20.0
    if obs.indicator_id == IndicatorId.VIX_TERM_STRUCTURE:
        if d.get("contango_calm_signal"):
            return 85.0
        pct = d.get("vix_5y_percentile")
        return 0.0 if pct is None else max(0.0, 40.0 - float(pct))
    if obs.indicator_id == IndicatorId.CREDIT_SPREAD_HY_OAS:
        pct = d.get("percentile_10y")
        return None if pct is None else max(0.0, min(100.0, 100.0 - float(pct) * 5.0))
    return None


def _ai_cycle_contribution(obs: IndicatorObservation) -> float | None:
    """Phase 1에서는 ai_cycle_score의 모든 구성 지표가 unavailable이라 항상 None을 반환한다
    (coverage 0% -> regime_classifier가 ai_regime을 INDETERMINATE로 처리). Phase 2에서 실제
    지표가 구현되면 details의 세부 키(매출성장률/Capex증가율/투자효율/반도체수요 등)를
    참조하도록 이 함수를 확장한다."""
    if obs.status != IndicatorStatus.OK or obs.value is None:
        return None
    return None


def _weighted_score(
    weights: list[tuple[IndicatorId, float]],
    contribution_fn: Callable[[IndicatorObservation], float | None],
    observations: dict[IndicatorId, IndicatorObservation],
) -> tuple[float | None, float]:
    """반환: (점수 0-100 또는 계산 불가 시 None, 커버리지 비율 0-1).

    누락/unavailable 지표는 0점으로 처리하지 않고 가용 지표의 가중치를 비례 재조정한다
    (원본 지침: "누락 지표를 0점으로 처리하지 않는다. 가용 지표의 가중치를 비례 재조정한다").
    """
    total_weight = sum(w for _, w in weights)
    available_weight = 0.0
    weighted_sum = 0.0
    for indicator_id, weight in weights:
        obs = observations.get(indicator_id)
        contribution = None if obs is None else contribution_fn(obs)
        if contribution is None:
            continue
        available_weight += weight
        weighted_sum += weight * contribution
    if available_weight == 0 or total_weight == 0:
        return None, 0.0
    return round(weighted_sum / available_weight, 1), round(available_weight / total_weight, 3)


def _compute_data_confidence(observations: dict[IndicatorId, IndicatorObservation]) -> float:
    """전체 10개 지표 중 정상 수집된 비율에서, 오래된(stale) 지표만큼 소폭 감점한다."""
    total = len(IndicatorId)
    if total == 0:
        return 0.0
    ok = sum(1 for obs in observations.values() if obs.status == IndicatorStatus.OK)
    stale = sum(
        1 for obs in observations.values() if obs.status == IndicatorStatus.OK and obs.is_stale
    )
    base = 100.0 * ok / total
    return round(max(0.0, min(100.0, base - _STALE_PENALTY_PER_INDICATOR * stale)), 1)


@dataclass
class ScoringResult:
    cooling_risk: float | None
    cooling_coverage: float
    overheating_risk: float | None
    overheating_coverage: float
    ai_cycle: float | None
    ai_coverage: float
    data_confidence: float
    confidence_level: ConfidenceLevel
    market_coverage: float


def compute_scores(observations: dict[IndicatorId, IndicatorObservation]) -> ScoringResult:
    cooling, cooling_cov = _weighted_score(
        COOLING_RISK_WEIGHTS, _cooling_contribution, observations
    )
    overheating, overheating_cov = _weighted_score(
        OVERHEATING_RISK_WEIGHTS, _overheating_contribution, observations
    )
    ai_cycle, ai_cov = _weighted_score(AI_CYCLE_WEIGHTS, _ai_cycle_contribution, observations)
    data_confidence = _compute_data_confidence(observations)

    market_coverage = round((cooling_cov + overheating_cov) / 2, 3)
    if market_coverage < _LOW_CONFIDENCE_COVERAGE_THRESHOLD:
        confidence_level = ConfidenceLevel.LOW
    elif market_coverage >= _HIGH_CONFIDENCE_COVERAGE_THRESHOLD:
        confidence_level = ConfidenceLevel.HIGH
    else:
        confidence_level = ConfidenceLevel.MEDIUM

    return ScoringResult(
        cooling_risk=cooling,
        cooling_coverage=cooling_cov,
        overheating_risk=overheating,
        overheating_coverage=overheating_cov,
        ai_cycle=ai_cycle,
        ai_coverage=ai_cov,
        data_confidence=data_confidence,
        confidence_level=confidence_level,
        market_coverage=market_coverage,
    )

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from investor_intel.models.common import ConfidenceLevel
from investor_intel.regime.models import IndicatorId, IndicatorObservation, IndicatorStatus

ContributionFn = Callable[[IndicatorObservation], float | None]

_LOW_CONFIDENCE_COVERAGE_THRESHOLD = 0.70
_HIGH_CONFIDENCE_COVERAGE_THRESHOLD = 0.90
_STALE_PENALTY_PER_INDICATOR = 10.0


def _linear_score(value: float, low: float, high: float) -> float:
    """value를 [low, high] 구간을 [0, 100]으로 선형 매핑한 뒤 클램프한다 - 성장률(%)류
    지표를 0-100 스코어로 변환할 때 공통으로 쓴다."""
    if high == low:
        return 50.0
    return min(100.0, max(0.0, (value - low) / (high - low) * 100.0))


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
    # AI_HYPERSCALER_CAPEX_EFFICIENCY(가중치 20%, "AI Capex 수익화 격차")는 여기서 일부러
    # 처리하지 않는다 - monetization_gap은 cloud/AI 매출 성장률이 있어야 계산 가능한데,
    # 그건 `regime analyze-ai`(Phase 2b, LLM)가 채우기 전까지 없다. 이 줄은 그동안 None으로
    # 남아 가중치 비례 재조정에서 자동 제외된다(버그가 아니라 의도된 상태).
    return None


# ai_cycle_score는 스펙상 세 가중치 줄(AI 매출성장/Capex증가/투자효율)이 전부
# ai_hyperscaler_capex_efficiency 지표 하나에서 나온다 - 지표 하나의 details 안에 있는
# 서로 다른 키를 각 줄이 참조해야 하므로, cooling/overheating과 달리 가중치 줄마다 별도
# contribution 함수를 둔다(_weighted_score가 줄 단위로 함수를 받도록 일반화되어 있음).
def _ai_hyperscaler_revenue_growth_contribution(obs: IndicatorObservation) -> float | None:
    """"하이퍼스케일러 AI 매출 성장" 줄. cloud/AI 세그먼트 매출 성장률은 Phase 2a의 무료
    수치 수집으로는 얻을 수 없다 - `regime analyze-ai`(Phase 2b, LLM)가
    details.cloud_ai_revenue_growth_yoy를 채우기 전까지 항상 None(가중치 비례 재조정으로
    자동 제외)이다."""
    if obs.status != IndicatorStatus.OK:
        return None
    growth = obs.details.get("cloud_ai_revenue_growth_yoy")
    return None if growth is None else _linear_score(float(growth), -10.0, 60.0)


def _ai_hyperscaler_capex_growth_contribution(obs: IndicatorObservation) -> float | None:
    """"하이퍼스케일러 Capex 증가" 줄. capex_growth_yoy는 Phase 2a(무료 Yahoo 재무제표)에서
    바로 계산된다."""
    if obs.status != IndicatorStatus.OK:
        return None
    growth = obs.details.get("capex_growth_yoy")
    return None if growth is None else _linear_score(float(growth), -10.0, 60.0)


def _ai_hyperscaler_capex_efficiency_contribution(obs: IndicatorObservation) -> float | None:
    """"Capex 투자 효율" 줄. capex_intensity(TTM CapEx/TTM 영업현금흐름)의 5년 백분위 평균을
    쓴다 - 백분위가 높을수록(자기 과거 대비 CapEx 비중이 큼) AI 투자가 활발한 국면으로 본다."""
    if obs.status != IndicatorStatus.OK:
        return None
    pct = obs.details.get("capex_intensity_percentile_avg")
    return None if pct is None else float(pct)


def _ai_semiconductor_demand_contribution(obs: IndicatorObservation) -> float | None:
    """"AI 반도체 실수요" 줄. TSM/NVDA/AVGO/MU 매출 성장률의 5년 백분위 평균(Phase 2a,
    무료)."""
    if obs.status != IndicatorStatus.OK:
        return None
    pct = obs.details.get("revenue_growth_yoy_percentile_avg")
    return None if pct is None else float(pct)


def _ai_eps_revision_contribution(obs: IndicatorObservation) -> float | None:
    """"AI 관련 실적 추정치 변화" 줄. EPS 수정 폭 지표 자체가 무료 데이터 소스가 없어
    항상 unavailable이므로 이 함수는 항상 None을 반환한다."""
    del obs
    return None


ContributionLine = tuple[IndicatorId, ContributionFn, float]

COOLING_RISK_WEIGHTS: list[ContributionLine] = [
    (IndicatorId.CREDIT_SPREAD_HY_OAS, _cooling_contribution, 0.20),
    (IndicatorId.CHICAGO_FED_ANFCI, _cooling_contribution, 0.15),
    (IndicatorId.EPS_REVISION_BREADTH, _cooling_contribution, 0.15),
    (IndicatorId.MARKET_BREADTH, _cooling_contribution, 0.15),
    (IndicatorId.VIX_TERM_STRUCTURE, _cooling_contribution, 0.10),
    (IndicatorId.EMPLOYMENT_COOLING, _cooling_contribution, 0.10),
    (IndicatorId.YIELD_CURVE_10Y3M, _cooling_contribution, 0.10),
    (IndicatorId.LEVERAGE_POSITIONING, _cooling_contribution, 0.05),
]

OVERHEATING_RISK_WEIGHTS: list[ContributionLine] = [
    (IndicatorId.LEVERAGE_POSITIONING, _overheating_contribution, 0.25),
    (IndicatorId.MARKET_BREADTH, _overheating_contribution, 0.20),
    (IndicatorId.VIX_TERM_STRUCTURE, _overheating_contribution, 0.15),
    (IndicatorId.CREDIT_SPREAD_HY_OAS, _overheating_contribution, 0.10),
    (IndicatorId.EPS_REVISION_BREADTH, _overheating_contribution, 0.10),
    (IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY, _overheating_contribution, 0.20),
]

AI_CYCLE_WEIGHTS: list[ContributionLine] = [
    (
        IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY,
        _ai_hyperscaler_revenue_growth_contribution,
        0.25,
    ),
    (
        IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY,
        _ai_hyperscaler_capex_growth_contribution,
        0.15,
    ),
    (
        IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY,
        _ai_hyperscaler_capex_efficiency_contribution,
        0.20,
    ),
    (IndicatorId.AI_SEMICONDUCTOR_DEMAND, _ai_semiconductor_demand_contribution, 0.25),
    (IndicatorId.EPS_REVISION_BREADTH, _ai_eps_revision_contribution, 0.15),
]


def _weighted_score(
    weights: list[ContributionLine],
    observations: dict[IndicatorId, IndicatorObservation],
) -> tuple[float | None, float]:
    """반환: (점수 0-100 또는 계산 불가 시 None, 커버리지 비율 0-1).

    누락/unavailable 지표는 0점으로 처리하지 않고 가용 지표의 가중치를 비례 재조정한다
    (원본 지침: "누락 지표를 0점으로 처리하지 않는다. 가용 지표의 가중치를 비례 재조정한다").
    가중치 줄마다 별도 contribution 함수를 받으므로, 같은 indicator_id가 여러 줄에 나오고
    각 줄이 그 지표 details의 서로 다른 필드를 참조하는 경우(ai_cycle_score)도 지원한다.
    """
    total_weight = sum(w for _, _, w in weights)
    available_weight = 0.0
    weighted_sum = 0.0
    for indicator_id, contribution_fn, weight in weights:
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


def build_cooling_risk_rationale(
    observations: dict[IndicatorId, IndicatorObservation],
) -> tuple[str, list[tuple[str, str]]]:
    """cooling_risk에 실제로 기여한(OK 상태) 지표들을 가중치 순으로 요약한다 - 종목
    스코어링의 macro_liquidity 카테고리가 "이 점수가 어디서 왔는지" 보여주는 데 쓰인다.
    반환 citation은 (label, url) 튜플로, 호출부가 scoring.models.Citation으로 감싼다
    (regime 모듈이 scoring 모듈을 의존하지 않도록)."""
    ranked = sorted(COOLING_RISK_WEIGHTS, key=lambda line: line[2], reverse=True)
    lines: list[str] = []
    citations: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for indicator_id, contribution_fn, _weight in ranked:
        obs = observations.get(indicator_id)
        if obs is None or contribution_fn(obs) is None:
            continue
        lines.append(
            f"- {obs.indicator_name}: {obs.value}{obs.unit} ({obs.observation_date.isoformat()})"
        )
        if obs.source_url not in seen_urls:
            seen_urls.add(obs.source_url)
            citations.append((obs.source_name, obs.source_url))
        if len(lines) >= 5:
            break
    return "\n".join(lines), citations


def compute_scores(observations: dict[IndicatorId, IndicatorObservation]) -> ScoringResult:
    cooling, cooling_cov = _weighted_score(COOLING_RISK_WEIGHTS, observations)
    overheating, overheating_cov = _weighted_score(OVERHEATING_RISK_WEIGHTS, observations)
    ai_cycle, ai_cov = _weighted_score(AI_CYCLE_WEIGHTS, observations)
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

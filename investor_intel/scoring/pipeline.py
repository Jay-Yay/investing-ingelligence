from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from investor_intel.models.config import (
    ConfidenceConfig,
    HardGateDefinition,
    HysteresisConfig,
    MetricSpec,
)
from investor_intel.scoring.categories import compute_category_score, compute_total_score
from investor_intel.scoring.confidence import compute_confidence
from investor_intel.scoring.earnings_revision import (
    EarningsRevisionInputs,
    build_earnings_revision_rationale,
    compute_earnings_revision_score,
)
from investor_intel.scoring.hard_gates import any_triggered, evaluate_hard_gates
from investor_intel.scoring.hysteresis import HysteresisState, next_signal
from investor_intel.scoring.models import (
    CategoryScore,
    Citation,
    DriverNote,
    Feature,
    StockScoreResult,
    ThesisStatus,
    TradeSignal,
)
from investor_intel.scoring.normalization import is_score_eligible, is_stale
from investor_intel.scoring.price_supply_demand import (
    PriceSupplyDemandMetrics,
    build_price_supply_demand_rationale,
    price_supply_demand_score,
)
from investor_intel.scoring.valuation_scenarios import (
    ValuationScenarios,
    build_valuation_rationale,
    valuation_score,
)

# 이 카테고리들은 sector_*.yaml의 features 목록이 비어 있고 전용 모듈/외부 입력이 직접 점수를
# 계산한다 (섹션 8: earnings_outlook/normalized_valuation/price_supply_demand는 metric 나열
# 방식이 아니라 별도 정량 로직이 필요하다고 명시되어 있다). macro_liquidity는 종목마다 따로
# 계산하지 않고 regime 모듈(시장 전체 cooling/overheating 점수)을 모든 종목이 공유해서
# 재사용한다 - macro_liquidity_score로 파이프라인에 직접 주입한다.
_SPECIAL_CATEGORIES = {
    "earnings_outlook",
    "normalized_valuation",
    "price_supply_demand",
    "macro_liquidity",
}


@dataclass
class StockScoringInputs:
    ticker: str
    as_of: date
    model_version: str
    category_weights: dict[str, float]
    metric_categories: dict[str, list[str]]  # 대분류 -> metric_id 목록 (_SPECIAL_CATEGORIES 제외)
    metric_specs: dict[str, MetricSpec]
    features: list[Feature]

    earnings_revision_inputs: EarningsRevisionInputs | None = None
    price_metrics: PriceSupplyDemandMetrics | None = None
    valuation_scenarios: ValuationScenarios | None = None
    current_price: float | None = None
    # regime.scoring.compute_scores()의 cooling_risk/overheating_risk를 "낙관적일수록 높은 점수"
    # 방향으로 변환해 넘긴다(예: 100 - cooling_risk). 시장 전체에 공통이라 모든 종목이 같은 날
    # 같은 값을 공유해도 된다 - 종목별로 다시 계산하지 않는다.
    macro_liquidity_score: float | None = None
    macro_liquidity_rationale: str = ""
    macro_liquidity_citations: list[Citation] = field(default_factory=list)

    hard_gate_definitions: list[HardGateDefinition] = field(default_factory=list)
    triggered_gate_ids: set[str] = field(default_factory=set)
    gate_evidence: dict[str, str] = field(default_factory=dict)

    confidence_config: ConfidenceConfig = field(default_factory=ConfidenceConfig)
    hysteresis_config: HysteresisConfig = field(
        default_factory=lambda: HysteresisConfig(
            entry_new_buy=72, maintain_buy=62, reduce_review=55, sell_review=45,
            cooldown_trading_days=5,
        )
    )

    currently_held: bool = False
    previous_hysteresis: HysteresisState | None = None
    days_since_last_change: int = 999

    thesis_status: ThesisStatus = ThesisStatus.MAINTAINED
    positive_drivers: list[DriverNote] = field(default_factory=list)
    negative_drivers: list[DriverNote] = field(default_factory=list)
    next_catalysts: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)

    score_change_1d: float | None = None
    score_change_1w: float | None = None
    score_change_1m: float | None = None


def _features_by_metric(features: list[Feature]) -> dict[str, Feature]:
    from investor_intel.scoring.normalization import latest_features_by_metric

    return latest_features_by_metric(features)


def compute_stock_score(inputs: StockScoringInputs) -> tuple[StockScoreResult, HysteresisState]:
    """섹션 6 최종 파이프라인. 이 함수는 이미 조달된 데이터(Feature 목록, 가격 히스토리 파생
    지표, 밸류에이션 시나리오 등)만 입력받고 어떤 네트워크 호출도 하지 않는다 - 실제 데이터
    수집은 CLI/pipeline/stock_score.py의 몫이다(테스트 가능성을 위해 순수 함수로 유지).
    """
    features_by_metric = _features_by_metric(inputs.features)

    category_scores: list[CategoryScore] = []
    contributing_features: list[Feature] = []
    missing_critical: list[str] = []

    for category, metric_ids in inputs.metric_categories.items():
        if category in _SPECIAL_CATEGORIES:
            continue
        weight = inputs.category_weights.get(category, 0.0)
        cs = compute_category_score(
            category, metric_ids, features_by_metric, inputs.metric_specs, weight, inputs.as_of
        )
        category_scores.append(cs)
        missing_critical.extend(cs.missing_metrics)
        for metric_id in metric_ids:
            feature = features_by_metric.get(metric_id)
            if (
                feature is not None
                and is_score_eligible(feature)[0]
                and not is_stale(feature, inputs.as_of)
            ):
                contributing_features.append(feature)

    if "earnings_outlook" in inputs.category_weights:
        earnings_score = None
        earnings_coverage = 0.0
        if inputs.earnings_revision_inputs is not None:
            earnings_score, earnings_coverage = compute_earnings_revision_score(
                inputs.earnings_revision_inputs
            )
        category_scores.append(
            CategoryScore(
                category="earnings_outlook",
                score=earnings_score,
                coverage=earnings_coverage,
                weight=inputs.category_weights.get("earnings_outlook", 0.0),
                contributing_features=1 if earnings_score is not None else 0,
                missing_metrics=[] if earnings_score is not None else ["earnings_revision_inputs"],
                rationale=(
                    build_earnings_revision_rationale(inputs.earnings_revision_inputs)
                    if inputs.earnings_revision_inputs is not None
                    else ""
                ),
            )
        )
        if earnings_score is None:
            missing_critical.append("earnings_revision_inputs")

    if "normalized_valuation" in inputs.category_weights:
        v_score = valuation_score(inputs.current_price, inputs.valuation_scenarios)
        category_scores.append(
            CategoryScore(
                category="normalized_valuation",
                score=v_score,
                coverage=1.0 if v_score is not None else 0.0,
                weight=inputs.category_weights.get("normalized_valuation", 0.0),
                contributing_features=1 if v_score is not None else 0,
                missing_metrics=[] if v_score is not None else ["valuation_scenarios"],
                rationale=build_valuation_rationale(
                    inputs.current_price, inputs.valuation_scenarios
                ),
            )
        )
        if v_score is None:
            missing_critical.append("valuation_scenarios")

    if "price_supply_demand" in inputs.category_weights:
        p_score = (
            price_supply_demand_score(inputs.price_metrics)
            if inputs.price_metrics is not None
            else None
        )
        p_rationale, p_citations = (
            build_price_supply_demand_rationale(inputs.price_metrics, inputs.ticker)
            if inputs.price_metrics is not None
            else ("", [])
        )
        category_scores.append(
            CategoryScore(
                category="price_supply_demand",
                score=p_score,
                coverage=1.0 if p_score is not None else 0.0,
                weight=inputs.category_weights.get("price_supply_demand", 0.0),
                contributing_features=1 if p_score is not None else 0,
                missing_metrics=[] if p_score is not None else ["price_metrics"],
                rationale=p_rationale,
                citations=p_citations,
            )
        )
        if p_score is None:
            missing_critical.append("price_metrics")

    if "macro_liquidity" in inputs.category_weights:
        category_scores.append(
            CategoryScore(
                category="macro_liquidity",
                score=inputs.macro_liquidity_score,
                coverage=1.0 if inputs.macro_liquidity_score is not None else 0.0,
                weight=inputs.category_weights.get("macro_liquidity", 0.0),
                contributing_features=1 if inputs.macro_liquidity_score is not None else 0,
                missing_metrics=(
                    [] if inputs.macro_liquidity_score is not None else ["macro_liquidity_score"]
                ),
                rationale=inputs.macro_liquidity_rationale,
                citations=inputs.macro_liquidity_citations,
            )
        )
        if inputs.macro_liquidity_score is None:
            missing_critical.append("macro_liquidity_score")

    total_score, _overall_coverage = compute_total_score(category_scores)
    confidence, confidence_level = compute_confidence(
        _overall_coverage, contributing_features, len(missing_critical), inputs.confidence_config
    )

    hard_gates = evaluate_hard_gates(
        inputs.hard_gate_definitions, inputs.triggered_gate_ids, inputs.gate_evidence
    )
    gate_triggered = any_triggered(hard_gates)

    hysteresis_state = next_signal(
        ticker=inputs.ticker,
        previous=inputs.previous_hysteresis,
        total_score=total_score,
        config=inputs.hysteresis_config,
        as_of=inputs.as_of,
        currently_held=inputs.currently_held,
        hard_gate_triggered=gate_triggered,
        days_since_last_change=inputs.days_since_last_change,
    )

    thesis_status = inputs.thesis_status
    if gate_triggered and thesis_status == ThesisStatus.MAINTAINED:
        thesis_status = ThesisStatus.IMPAIRED

    result = StockScoreResult(
        ticker=inputs.ticker,
        as_of=inputs.as_of,
        model_version=inputs.model_version,
        total_score=total_score,
        score_change_1d=inputs.score_change_1d,
        score_change_1w=inputs.score_change_1w,
        score_change_1m=inputs.score_change_1m,
        category_scores=category_scores,
        confidence=confidence,
        confidence_level=confidence_level,
        thesis_status=thesis_status,
        signal=hysteresis_state.signal,
        hard_gates=hard_gates,
        positive_drivers=inputs.positive_drivers,
        negative_drivers=inputs.negative_drivers,
        next_catalysts=inputs.next_catalysts,
        invalidation_conditions=inputs.invalidation_conditions,
        data_freshness_days=None,
        missing_critical_data=missing_critical,
    )
    return result, hysteresis_state


def new_buy_signal_allowed(
    result: StockScoreResult,
    min_confidence: float,
    min_total_score: float,
    consecutive_score_increases: int,
    min_consecutive_increases_required: int,
    secondary_confirmations_met: int,
    min_secondary_confirmations_required: int,
) -> bool:
    """섹션 14 "신규 매수 신호 조건을 모두 충족" 체크. 개별 판정 근거(연속 상승 횟수, 2차
    확인 신호 충족 개수)는 호출부(evaluation/report 계층)가 스냅샷 이력을 스캔해 계산한 뒤
    넘긴다 - 이 함수 자체는 순수 조건 판정만 한다."""
    if result.total_score is None or result.total_score < min_total_score:
        return False
    if result.confidence < min_confidence:
        return False
    if consecutive_score_increases < min_consecutive_increases_required:
        return False
    if result.thesis_status in (ThesisStatus.IMPAIRED, ThesisStatus.INVALIDATED):
        return False
    if any_triggered(result.hard_gates):
        return False
    if secondary_confirmations_met < min_secondary_confirmations_required:
        return False
    return result.signal in (TradeSignal.STRONG_BUY_CANDIDATE, TradeSignal.ACCUMULATE_CANDIDATE)


def reduce_or_sell_review_triggered(
    result: StockScoreResult, consecutive_eps_cut_quarters: int
) -> bool:
    """섹션 14 "비중 축소 또는 매도 신호는 다음 중 하나가 발생할 때 검토"."""
    if result.total_score is not None and result.total_score < 50:
        return True
    if result.thesis_status in (ThesisStatus.IMPAIRED, ThesisStatus.INVALIDATED):
        return True
    if any_triggered(result.hard_gates):
        return True
    if consecutive_eps_cut_quarters >= 2:
        return True
    return result.signal in (TradeSignal.REDUCE_REVIEW, TradeSignal.SELL_REVIEW)

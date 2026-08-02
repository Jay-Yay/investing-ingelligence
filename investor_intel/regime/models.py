from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from investor_intel.models.common import ConfidenceLevel


class IndicatorId(StrEnum):
    CREDIT_SPREAD_HY_OAS = "credit_spread_hy_oas"
    CHICAGO_FED_ANFCI = "chicago_fed_anfci"
    YIELD_CURVE_10Y3M = "yield_curve_10y3m"
    EMPLOYMENT_COOLING = "employment_cooling"
    VIX_TERM_STRUCTURE = "vix_term_structure"
    MARKET_BREADTH = "market_breadth"
    LEVERAGE_POSITIONING = "leverage_positioning"
    EPS_REVISION_BREADTH = "eps_revision_breadth"
    AI_HYPERSCALER_CAPEX_EFFICIENCY = "ai_hyperscaler_capex_efficiency"
    AI_SEMICONDUCTOR_DEMAND = "ai_semiconductor_demand"


class IndicatorFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class IndicatorStatus(StrEnum):
    OK = "ok"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class SignalStatus(StrEnum):
    NORMAL = "normal"
    WATCH = "watch"
    CONFIRMED = "confirmed"
    RESOLVED = "resolved"
    UNAVAILABLE = "unavailable"


class SignalDirection(StrEnum):
    COOLING = "cooling"
    OVERHEATING = "overheating"
    IMPROVING = "improving"
    NEUTRAL = "neutral"


class MarketRegime(StrEnum):
    HEALTHY_RISK_ON = "HEALTHY_RISK_ON"
    OVERHEATED = "OVERHEATED"
    LATE_CYCLE_DIVERGENCE = "LATE_CYCLE_DIVERGENCE"
    COOLING = "COOLING"
    STRESS = "STRESS"
    NEUTRAL = "NEUTRAL"
    INDETERMINATE = "INDETERMINATE"


class AiRegime(StrEnum):
    AI_EXPANSION = "AI_EXPANSION"
    AI_OVERINVESTMENT_RISK = "AI_OVERINVESTMENT_RISK"
    NEUTRAL = "NEUTRAL"
    INDETERMINATE = "INDETERMINATE"


class IndicatorObservation(BaseModel):
    """지표 하나의 최신 관측값 - history_store JSONL의 한 줄이 이 모델 하나에 대응한다.

    value가 None이면 status는 반드시 unavailable 또는 error다 (원본 지침 #2: 추정값을
    만들지 않는다 - 데이터가 없으면 null로 남긴다).
    """

    indicator_id: IndicatorId
    indicator_name: str
    value: float | None
    unit: str
    observation_date: date
    release_date: date | None
    fetched_at: datetime
    source_name: str
    source_url: str
    frequency: IndicatorFrequency
    data_age_days: int
    is_stale: bool
    is_revised: bool | None
    status: IndicatorStatus
    details: dict[str, Any] = {}
    """지표별 진단 수치(예: 20거래일 변화, 10년 백분위, z-score, 냉각/과열 신호 플래그, 종목별
    세부 breakdown). 핵심 스키마(value/unit 등)는 지표마다 동일하게 유지하되, 스코어링/리포트가
    참조하는 세부 필드는 지표마다 달라 dict로 둔다 - 각 collector 모듈 docstring에 실제 키를
    문서화한다."""


class ScoreBreakdown(BaseModel):
    cooling_risk: float | None
    overheating_risk: float | None
    ai_cycle: float | None
    data_confidence: float


class RegimeSignal(BaseModel):
    indicator_id: IndicatorId
    status: SignalStatus
    direction: SignalDirection
    severity: int  # 0-100
    reason: str
    observation_date: date | None
    data_age_days: int | None


class DataQuality(BaseModel):
    coverage_ratio: float
    stale_indicators: list[str] = []
    unavailable_indicators: list[str] = []
    errors: list[str] = []


class DailyRegimeReport(BaseModel):
    as_of: date
    market_regime: MarketRegime
    ai_regime: AiRegime
    scores: ScoreBreakdown
    confidence_level: ConfidenceLevel
    signals: list[RegimeSignal] = []
    new_releases: list[str] = []
    warnings: list[str] = []
    data_quality: DataQuality


class RegimeSnapshot(BaseModel):
    """processed/<date>.json에 저장되는 실제 내용.

    사람이 보는 리포트(report)뿐 아니라, 다음날 신호 지속성 판정(signal_state)과 신규 발표
    감지(report_renderer.detect_new_releases)에 필요한 그날의 지표별 원본 관측치
    (observations)도 함께 보존한다 - 이게 없으면 다음날 "어제 값"을 다시 계산할 방법이
    없어진다(과거 지표값은 개정될 수 있어 history JSONL의 "최신값"이 어제 시점에 우리가
    실제로 봤던 값과 다를 수 있기 때문).
    """

    report: DailyRegimeReport
    observations: dict[IndicatorId, IndicatorObservation]

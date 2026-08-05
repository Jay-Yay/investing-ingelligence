from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel

from investor_intel.models.common import ConfidenceLevel


class FactType(StrEnum):
    """섹션 5 출처 신뢰도 규칙과 결합해서 쓰인다 - RUMOR/OPINION은 복수의 신뢰 가능한 출처로
    확인되기 전까지 점수에 직접 반영되지 않는다(categories.py의 필터 참고)."""

    REPORTED_FACT = "reported_fact"
    COMPANY_GUIDANCE = "company_guidance"
    CONSENSUS = "consensus"
    ESTIMATE = "estimate"
    OPINION = "opinion"
    RUMOR = "rumor"


class SourceTier(StrEnum):
    """섹션 5 출처 우선순위 1~5를 그대로 옮긴 것."""

    OFFICIAL = "official"  # 1순위: 기업 IR/실적/공시/중앙은행/정부기관
    INDUSTRY = "industry"  # 2순위: TrendForce/Gartner/IDC/Omdia/IEA/SEMI 등
    NEWS = "news"  # 3순위: Reuters/Bloomberg/FT/WSJ 등
    BROKER = "broker"  # 4순위: 증권사/IB 리포트
    SOCIAL = "social"  # 5순위: 소셜미디어/익명 업계 정보


class TradeSignal(StrEnum):
    STRONG_BUY_CANDIDATE = "strong_buy_candidate"
    ACCUMULATE_CANDIDATE = "accumulate_candidate"
    HOLD_WATCH = "hold_watch"
    REDUCE_REVIEW = "reduce_review"
    SELL_REVIEW = "sell_review"


class ThesisStatus(StrEnum):
    MAINTAINED = "maintained"
    WATCH = "watch"
    IMPAIRED = "impaired"
    INVALIDATED = "invalidated"


class Feature(BaseModel):
    """섹션 4 데이터 모델. 하나의 관측된 수치 또는 정성 판단 하나에 대응한다.

    value가 None이면 이 feature는 missing으로 취급되고 categories.py의 가중치 재조정 로직이
    자동으로 처리한다 - 추정값을 만들어 채우지 않는다. qualitative_trend류 metric은 value 대신
    details["trend"]("개선"/"악화"/"횡보")를 쓴다(metric_normalizers.py 참고).
    """

    ticker: str
    metric: str
    value: float | None
    unit: str
    period: str
    published_at: datetime
    retrieved_at: datetime
    source_name: str
    source_url: str
    source_tier: SourceTier
    fact_type: FactType
    confidence: float  # 0-1, 이 feature 하나의 신뢰도 (집계된 카테고리/총점 confidence와 다름)
    affected_categories: list[str] = []
    max_age_days: int | None = None  # None이면 유효기간 없음(예: 정성적 경쟁우위 판단)
    details: dict[str, str] = {}


class Citation(BaseModel):
    label: str
    url: str


class DriverNote(BaseModel):
    """섹션 6/7 긍정/부정 요인 하나. claim은 한 줄 요약, rationale은 왜 이게 판단에
    영향을 주는지에 대한 3-5줄 배경 설명 - 숫자만 던지고 끝내지 않기 위함."""

    claim: str
    rationale: str
    source_url: str


class CategoryScore(BaseModel):
    category: str
    score: float | None  # 0-100, 계산 불가 시 None
    coverage: float  # 0-1, 이 카테고리에 정의된 feature 대비 실제 확보된 비중(가중치 기준)
    weight: float  # 이 카테고리의 대분류 가중치 (설정 파일 값, 0-100 스케일)
    contributing_features: int
    missing_metrics: list[str] = []
    # 이 점수가 어떤 근거로 나왔는지에 대한 3-5줄 설명과 그 출처 - "숫자만 있고 배경이 없다"는
    # 문제를 해결하기 위해 추가됨(section 2가 근거 없이 숫자만 보여주던 문제).
    rationale: str = ""
    citations: list[Citation] = []


class HardGateHit(BaseModel):
    gate_id: str
    description: str
    triggered: bool
    evidence: str = ""


class SecondaryConfirmation(BaseModel):
    signal_id: str
    met: bool
    detail: str = ""


class StockScoreResult(BaseModel):
    """섹션 6 최종 반환 형식. `stock_scoring.py`의 유일한 출력 - 리포트 렌더러와 스냅샷 저장이
    전부 이 모델 하나만 참조한다."""

    ticker: str
    as_of: date
    model_version: str
    total_score: float | None
    score_change_1d: float | None = None
    score_change_1w: float | None = None
    score_change_1m: float | None = None
    category_scores: list[CategoryScore]
    confidence: float
    confidence_level: ConfidenceLevel
    thesis_status: ThesisStatus
    signal: TradeSignal | None
    hard_gates: list[HardGateHit] = []
    secondary_confirmations: list[SecondaryConfirmation] = []
    positive_drivers: list[DriverNote] = []
    negative_drivers: list[DriverNote] = []
    next_catalysts: list[str] = []
    invalidation_conditions: list[str] = []
    data_freshness_days: int | None = None
    missing_critical_data: list[str] = []

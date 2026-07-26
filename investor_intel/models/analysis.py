from __future__ import annotations

from pydantic import BaseModel

from investor_intel.models.common import (
    ConfidenceLevel,
    DecisionStatus,
    Direction,
    FactOrOpinion,
    RecommendationRating,
    TenbaggerTier,
    ThesisShift,
)


class Claim(BaseModel):
    claim: str
    evidence: list[str]
    counter_evidence: list[str] = []
    assets: list[str] = []
    fact_or_opinion: FactOrOpinion
    direction: Direction
    confidence: ConfidenceLevel


class ExtractionResult(BaseModel):
    claims: list[Claim]


class PositionSignal(BaseModel):
    """포트폴리오 모니터 1회 호출로 보유 종목 하나에 대해 나오는 판단 단위.

    signal/signal_strength는 LLM 원본 값이 아니라 orchestrator에서 사후 검증(70점 미만 다운그레이드,
    가드레일 캡 적용)을 거친 뒤의 최종 값이 저장된다.
    """

    symbol: str
    new_facts: list[str] = []
    thesis_shift: ThesisShift
    causal_chain: str
    expectation_vs_price: str
    counter_evidence: list[str] = []
    decision_status: DecisionStatus = DecisionStatus.COMPLETE
    signal: RecommendationRating | None = None
    signal_strength: int = 0
    action_conditions: str = ""
    next_check_conditions: str = ""


class PositionSignalBatch(BaseModel):
    signals: list[PositionSignal]


class TenbaggerScoreBreakdown(BaseModel):
    market_expansion: int  # 0-15
    earnings_inflection: int  # 0-20
    unit_economics: int  # 0-15
    competitive_moat: int  # 0-15
    attention_gap: int  # 0-10
    valuation_path: int  # 0-15
    financial_survival: int  # 0-10


class TenbaggerCandidate(BaseModel):
    """total_score/tier는 LLM이 매긴 값이 아니라 scores 합계로부터 코드가 재계산한 값이 최종
    저장된다 — 점수 산술을 LLM에 맡기지 않기 위함."""

    symbol_or_company: str
    scores: TenbaggerScoreBreakdown
    total_score: int = 0
    tier: TenbaggerTier = TenbaggerTier.EXCLUDED
    ten_bagger_path: str
    biggest_risk: str
    hard_excluded: bool = False
    exclusion_reason: str = ""


class TenbaggerCandidateBatch(BaseModel):
    candidates: list[TenbaggerCandidate]


class TenbaggerScenario(BaseModel):
    """Q1/Q2: 시총 target_multiple배 달성에 필요한 매출·순이익과, years년 내 그 경로가
    최근 실제 성장 추세로 가능한 영역인지."""

    target_multiple: float
    years: float
    derate_factor: float  # 미래 밸류에이션 배수를 현재 대비 몇 배로 가정하는지 (1.0=배수 유지)
    market_cap: float
    ttm_revenue: float | None
    ttm_net_income: float | None
    ps_ratio: float | None
    pe_ratio: float | None
    required_revenue: float | None
    required_net_income: float | None
    required_cagr_revenue: float | None
    recent_avg_yoy_growth: float | None
    feasible_by_trend: bool | None


class TenbaggerGrowthAcceleration(BaseModel):
    """Q3 프록시: 매출 YoY 성장률이 직전 분기 대비 가속/둔화 중인지. 실제 KPI 명칭·사업적
    의미는 정성 리서치가 필요하다 - 여기서는 매출 성장의 방향성만 계산한다."""

    latest_yoy_growth: float
    prev_yoy_growth: float
    accelerating: bool
    delta: float


class TenbaggerMarginTrend(BaseModel):
    """Q7: 성장할수록 영업이익률이 개선되는지. Q10 프록시: 평균-표준편차를 조기경보 임계치로
    사용."""

    slope_per_quarter: float
    trend: str  # "개선" | "악화" | "횡보"
    latest_margin: float
    mean_margin: float
    std_margin: float
    warning_threshold_margin: float


class TenbaggerSurvival(BaseModel):
    """Q9: 촉매가 발생하기 전까지 추가 증자 없이 생존 가능한가.

    실제 FCF(OCF-CapEx)가 흑자인지를 우선 기준으로 삼는다 - OCF만 보면 대규모 고객
    선수금·일회성 유입이 있는 스케일업 기업(CapEx가 매출의 몇 배인 경우 등)에서 생존
    가능성을 과대평가하기 쉽다.
    """

    current_ratio: float | None
    debt_to_equity: float | None
    ttm_operating_cash_flow: float | None
    ttm_capital_expenditure: float | None  # 항상 양수(지출 규모)로 정규화
    ttm_free_cash_flow: float | None
    cash: float | None
    runway_quarters: float | None
    verdict: str


class TenbaggerVerification(BaseModel):
    """10x_verifier: 텐베거 가설 중 정량적으로 계산 가능한 부분(Q1/Q2/Q3프록시/Q7/Q9/Q10프록시).

    컨센서스 오류(Q5)·촉매(Q6)·경쟁우위(Q8) 등 정성적 질문은 이 모델의 범위 밖이며, 별도
    리서치로 보완해야 한다 - tenbagger_discovery(LLM 채점 파이프라인)와는 의도적으로 분리된
    보완 도구다.
    """

    symbol: str
    currency: str
    scenario: TenbaggerScenario
    growth_acceleration: TenbaggerGrowthAcceleration | None
    margin_trend: TenbaggerMarginTrend | None
    survival: TenbaggerSurvival

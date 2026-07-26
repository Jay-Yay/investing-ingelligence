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

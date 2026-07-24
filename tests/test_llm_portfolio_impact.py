from investor_intel.llm.portfolio_impact import apply_recommendation_cap, suggest_rating_from_claims
from investor_intel.models.analysis import Claim
from investor_intel.models.common import (
    ConfidenceLevel,
    Direction,
    FactOrOpinion,
    RecommendationRating,
)


def _claim(direction: Direction, confidence: ConfidenceLevel) -> Claim:
    return Claim(
        claim="claim text",
        evidence=["evidence"],
        fact_or_opinion=FactOrOpinion.FACT,
        direction=direction,
        confidence=confidence,
    )


def test_suggest_rating_majority_bullish_is_buy() -> None:
    claims = [
        _claim(Direction.BULLISH, ConfidenceLevel.HIGH),
        _claim(Direction.BULLISH, ConfidenceLevel.MEDIUM),
        _claim(Direction.BEARISH, ConfidenceLevel.HIGH),
    ]
    assert suggest_rating_from_claims(claims) == RecommendationRating.BUY


def test_suggest_rating_majority_bearish_is_reduce() -> None:
    claims = [
        _claim(Direction.BEARISH, ConfidenceLevel.HIGH),
        _claim(Direction.BEARISH, ConfidenceLevel.MEDIUM),
        _claim(Direction.BULLISH, ConfidenceLevel.HIGH),
    ]
    assert suggest_rating_from_claims(claims) == RecommendationRating.REDUCE


def test_suggest_rating_tie_is_hold() -> None:
    claims = [
        _claim(Direction.BULLISH, ConfidenceLevel.HIGH),
        _claim(Direction.BEARISH, ConfidenceLevel.HIGH),
    ]
    assert suggest_rating_from_claims(claims) == RecommendationRating.HOLD


def test_suggest_rating_no_claims_is_hold() -> None:
    assert suggest_rating_from_claims([]) == RecommendationRating.HOLD


def test_suggest_rating_ignores_low_confidence_claims() -> None:
    claims = [
        _claim(Direction.BULLISH, ConfidenceLevel.LOW),
        _claim(Direction.BEARISH, ConfidenceLevel.LOW),
    ]
    # both low-confidence -> excluded from the vote -> no claims counted -> HOLD
    assert suggest_rating_from_claims(claims) == RecommendationRating.HOLD


def test_apply_recommendation_cap_pulls_down_bullish_suggestion() -> None:
    result = apply_recommendation_cap(
        RecommendationRating.STRONG_BUY, cap=RecommendationRating.HOLD
    )
    assert result == RecommendationRating.HOLD


def test_apply_recommendation_cap_none_is_noop() -> None:
    result = apply_recommendation_cap(RecommendationRating.STRONG_BUY, cap=None)
    assert result == RecommendationRating.STRONG_BUY


def test_apply_recommendation_cap_does_not_raise_suggestion_above_cap() -> None:
    # cap is more bullish than the suggestion -> suggestion wins unchanged
    result = apply_recommendation_cap(RecommendationRating.SELL, cap=RecommendationRating.BUY)
    assert result == RecommendationRating.SELL

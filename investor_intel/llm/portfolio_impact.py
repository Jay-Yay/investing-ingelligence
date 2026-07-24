from __future__ import annotations

from investor_intel.models.analysis import Claim
from investor_intel.models.common import ConfidenceLevel, Direction, RecommendationRating

RATING_ORDER: list[RecommendationRating] = [
    RecommendationRating.SELL,
    RecommendationRating.REDUCE,
    RecommendationRating.HOLD,
    RecommendationRating.BUY,
    RecommendationRating.STRONG_BUY,
]

_COUNTED_CONFIDENCE = {ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM}


def suggest_rating_from_claims(claims: list[Claim]) -> RecommendationRating:
    counted = [claim for claim in claims if claim.confidence in _COUNTED_CONFIDENCE]
    bullish = sum(1 for claim in counted if claim.direction == Direction.BULLISH)
    bearish = sum(1 for claim in counted if claim.direction == Direction.BEARISH)

    if bullish > bearish:
        return RecommendationRating.BUY
    if bearish > bullish:
        return RecommendationRating.REDUCE
    return RecommendationRating.HOLD


def apply_recommendation_cap(
    suggested: RecommendationRating, cap: RecommendationRating | None
) -> RecommendationRating:
    if cap is None:
        return suggested
    if RATING_ORDER.index(suggested) <= RATING_ORDER.index(cap):
        return suggested
    return cap

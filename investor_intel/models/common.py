from __future__ import annotations

from enum import StrEnum


class SourceType(StrEnum):
    NAVER = "naver"
    TELEGRAM = "telegram"
    SEC_13F = "sec_13f"
    SEC_FILING = "sec_filing"
    DART = "dart"
    ESSAY = "essay"
    IB_INSIGHTS = "ib_insights"


class ContentCaptureMode(StrEnum):
    FULL = "full"
    EXCERPT = "excerpt"
    METADATA_ONLY = "metadata_only"


class Direction(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FactOrOpinion(StrEnum):
    FACT = "fact"
    OPINION = "opinion"
    FORECAST = "forecast"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"


class DecisionStatus(StrEnum):
    COMPLETE = "complete"
    PENDING = "pending"


class RecommendationRating(StrEnum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"

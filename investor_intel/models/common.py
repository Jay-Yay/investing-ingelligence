from __future__ import annotations

from enum import Enum


class SourceType(str, Enum):
    NAVER = "naver"
    TELEGRAM = "telegram"
    SEC_13F = "sec_13f"
    SEC_FILING = "sec_filing"
    DART = "dart"
    ESSAY = "essay"


class ContentCaptureMode(str, Enum):
    FULL = "full"
    EXCERPT = "excerpt"
    METADATA_ONLY = "metadata_only"


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FactOrOpinion(str, Enum):
    FACT = "fact"
    OPINION = "opinion"
    FORECAST = "forecast"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"


class DecisionStatus(str, Enum):
    COMPLETE = "complete"
    PENDING = "pending"


class RecommendationRating(str, Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"

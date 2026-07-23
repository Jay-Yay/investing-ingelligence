from investor_intel.models.common import (
    ContentCaptureMode,
    RecommendationRating,
    SourceType,
)


def test_source_type_values() -> None:
    assert SourceType("telegram") is SourceType.TELEGRAM
    assert SourceType.SEC_13F.value == "sec_13f"
    assert SourceType.SEC_FILING.value == "sec_filing"


def test_recommendation_rating_values() -> None:
    assert {r.value for r in RecommendationRating} == {
        "strong_buy",
        "buy",
        "hold",
        "reduce",
        "sell",
    }


def test_content_capture_mode_values() -> None:
    assert ContentCaptureMode("metadata_only") is ContentCaptureMode.METADATA_ONLY

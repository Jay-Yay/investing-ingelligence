from datetime import UTC, datetime

from investor_intel.models.config import MetricSpec
from investor_intel.scoring.metric_normalizers import normalize_feature
from investor_intel.scoring.models import FactType, Feature, SourceTier


def _feature(value: float | None = None, trend: str | None = None) -> Feature:
    return Feature(
        ticker="000660.KS",
        metric="test_metric",
        value=value,
        unit="pct",
        period="2026Q2",
        published_at=datetime(2026, 7, 30, tzinfo=UTC),
        retrieved_at=datetime(2026, 8, 2, tzinfo=UTC),
        source_name="test",
        source_url="https://example.com",
        source_tier=SourceTier.BROKER,
        fact_type=FactType.ESTIMATE,
        confidence=0.8,
        details={"trend": trend} if trend else {},
    )


def test_growth_rate_pct_maps_bad_to_zero_and_good_to_hundred() -> None:
    spec = MetricSpec(kind="growth_rate_pct", bad=-15, good=15)
    assert normalize_feature(_feature(-15), spec) == 0.0
    assert normalize_feature(_feature(15), spec) == 100.0
    assert normalize_feature(_feature(0), spec) == 50.0


def test_growth_rate_pct_clamps_beyond_bounds() -> None:
    spec = MetricSpec(kind="growth_rate_pct", bad=-15, good=15)
    assert normalize_feature(_feature(100), spec) == 100.0
    assert normalize_feature(_feature(-100), spec) == 0.0


def test_inverse_growth_rate_pct_inverts_direction() -> None:
    spec = MetricSpec(kind="inverse_growth_rate_pct", bad=25, good=5)
    assert normalize_feature(_feature(25), spec) == 0.0
    assert normalize_feature(_feature(5), spec) == 100.0


def test_percent_passthrough_handles_both_0_1_and_0_100_scales() -> None:
    spec = MetricSpec(kind="percent_passthrough")
    assert normalize_feature(_feature(0.62), spec) == 62.0
    assert normalize_feature(_feature(62.0), spec) == 62.0


def test_boolean_kind() -> None:
    spec = MetricSpec(kind="boolean")
    assert normalize_feature(_feature(1.0), spec) == 100.0
    assert normalize_feature(_feature(0.0), spec) == 0.0


def test_inverse_months_lower_is_better() -> None:
    spec = MetricSpec(kind="inverse_months", good=1.0, bad=6.0)
    assert normalize_feature(_feature(1.0), spec) == 100.0
    assert normalize_feature(_feature(6.0), spec) == 0.0


def test_qualitative_trend_uses_details_not_value() -> None:
    spec = MetricSpec(kind="qualitative_trend")
    assert normalize_feature(_feature(trend="개선"), spec) == 85.0
    assert normalize_feature(_feature(trend="악화"), spec) == 15.0
    assert normalize_feature(_feature(trend="횡보"), spec) == 50.0


def test_missing_value_returns_none_not_a_default() -> None:
    spec = MetricSpec(kind="growth_rate_pct", bad=-15, good=15)
    assert normalize_feature(_feature(value=None), spec) is None


def test_qualitative_trend_missing_returns_none() -> None:
    spec = MetricSpec(kind="qualitative_trend")
    assert normalize_feature(_feature(), spec) is None

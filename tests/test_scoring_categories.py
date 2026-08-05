from datetime import UTC, date, datetime

from investor_intel.models.config import MetricSpec
from investor_intel.scoring.categories import compute_category_score, compute_total_score
from investor_intel.scoring.models import CategoryScore, Citation, FactType, Feature, SourceTier

_AS_OF = date(2026, 8, 2)
_SPECS = {
    "metric_a": MetricSpec(kind="growth_rate_pct", bad=-10, good=10),
    "metric_b": MetricSpec(kind="percent_passthrough"),
}


def _feature(
    metric: str,
    value: float,
    tier: SourceTier = SourceTier.BROKER,
    fact_type: FactType = FactType.ESTIMATE,
    max_age_days: int | None = 90,
    published_at: datetime = datetime(2026, 7, 30, tzinfo=UTC),
) -> Feature:
    return Feature(
        ticker="X",
        metric=metric,
        value=value,
        unit="pct",
        period="2026Q2",
        published_at=published_at,
        retrieved_at=datetime(2026, 8, 2, tzinfo=UTC),
        source_name="test",
        source_url="https://example.com",
        source_tier=tier,
        fact_type=fact_type,
        confidence=0.8,
        max_age_days=max_age_days,
    )


def test_full_coverage_averages_all_metrics() -> None:
    features = {"metric_a": _feature("metric_a", 10.0), "metric_b": _feature("metric_b", 50.0)}
    result = compute_category_score("cat", ["metric_a", "metric_b"], features, _SPECS, 25.0, _AS_OF)
    assert result.score == 75.0  # (100 + 50) / 2
    assert result.coverage == 1.0
    assert result.contributing_features == 2
    assert result.missing_metrics == []


def test_missing_metric_reweights_not_zero_fills() -> None:
    features = {"metric_a": _feature("metric_a", 10.0)}
    result = compute_category_score("cat", ["metric_a", "metric_b"], features, _SPECS, 25.0, _AS_OF)
    assert result.score == 100.0  # only metric_a contributes, not averaged against a phantom 0
    assert result.coverage == 0.5
    assert result.missing_metrics == ["metric_b"]


def test_no_metrics_available_returns_none_score() -> None:
    result = compute_category_score("cat", ["metric_a", "metric_b"], {}, _SPECS, 25.0, _AS_OF)
    assert result.score is None
    assert result.coverage == 0.0


def test_empty_metric_list_returns_none_immediately() -> None:
    result = compute_category_score("cat", [], {}, _SPECS, 25.0, _AS_OF)
    assert result.score is None
    assert result.contributing_features == 0


def test_stale_feature_excluded_via_max_age_days() -> None:
    old_feature = _feature(
        "metric_a", 10.0, max_age_days=30, published_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    features = {"metric_a": old_feature, "metric_b": _feature("metric_b", 50.0)}
    result = compute_category_score("cat", ["metric_a", "metric_b"], features, _SPECS, 25.0, _AS_OF)
    assert result.contributing_features == 1
    assert "metric_a" in result.missing_metrics


def test_rumor_and_social_features_are_excluded_from_score() -> None:
    rumor_feature = _feature("metric_a", 10.0, fact_type=FactType.RUMOR)
    social_feature = _feature("metric_b", 50.0, tier=SourceTier.SOCIAL)
    features = {"metric_a": rumor_feature, "metric_b": social_feature}
    result = compute_category_score("cat", ["metric_a", "metric_b"], features, _SPECS, 25.0, _AS_OF)
    assert result.score is None
    assert result.contributing_features == 0
    assert set(result.missing_metrics) == {"metric_a", "metric_b"}


def test_undefined_metric_spec_is_treated_as_missing() -> None:
    features = {"metric_a": _feature("metric_a", 10.0)}
    result = compute_category_score("cat", ["metric_a", "metric_c"], features, _SPECS, 25.0, _AS_OF)
    assert result.missing_metrics == ["metric_c"]


def test_compute_total_score_reweights_missing_categories() -> None:
    scores = [
        CategoryScore(category="a", score=80.0, coverage=1.0, weight=50.0, contributing_features=1),
        CategoryScore(category="b", score=None, coverage=0.0, weight=50.0, contributing_features=0),
    ]
    total, coverage = compute_total_score(scores)
    assert total == 80.0  # only category "a" contributes; not averaged with a phantom 0 for "b"
    assert coverage == 0.5


def test_compute_total_score_all_missing_returns_none() -> None:
    scores = [
        CategoryScore(category="a", score=None, coverage=0.0, weight=50.0, contributing_features=0),
    ]
    total, coverage = compute_total_score(scores)
    assert total is None
    assert coverage == 0.0


def test_same_input_produces_same_score_deterministic() -> None:
    features = {"metric_a": _feature("metric_a", 10.0), "metric_b": _feature("metric_b", 50.0)}
    r1 = compute_category_score("cat", ["metric_a", "metric_b"], features, _SPECS, 25.0, _AS_OF)
    r2 = compute_category_score("cat", ["metric_a", "metric_b"], features, _SPECS, 25.0, _AS_OF)
    assert r1.score == r2.score
    assert r1.coverage == r2.coverage


def test_rationale_lists_only_contributing_features_with_source_links() -> None:
    features = {"metric_a": _feature("metric_a", 10.0), "metric_b": _feature("metric_b", 50.0)}
    result = compute_category_score("cat", ["metric_a", "metric_b"], features, _SPECS, 25.0, _AS_OF)
    assert "metric_a" in result.rationale
    assert "[test](https://example.com)" in result.rationale
    assert result.citations == [Citation(label="test", url="https://example.com")]


def test_rationale_excludes_missing_and_ineligible_features() -> None:
    rumor_feature = _feature("metric_a", 10.0, fact_type=FactType.RUMOR)
    features = {"metric_a": rumor_feature, "metric_b": _feature("metric_b", 50.0)}
    result = compute_category_score("cat", ["metric_a", "metric_b"], features, _SPECS, 25.0, _AS_OF)
    assert "metric_a" not in result.rationale
    assert "metric_b" in result.rationale

from datetime import UTC, datetime

from investor_intel.models.common import ConfidenceLevel
from investor_intel.models.config import ConfidenceConfig
from investor_intel.scoring.confidence import compute_confidence
from investor_intel.scoring.models import FactType, Feature, SourceTier

_CONFIG = ConfidenceConfig()


def _feature(tier: SourceTier) -> Feature:
    return Feature(
        ticker="X",
        metric="m",
        value=1.0,
        unit="pct",
        period="2026Q2",
        published_at=datetime(2026, 7, 30, tzinfo=UTC),
        retrieved_at=datetime(2026, 8, 2, tzinfo=UTC),
        source_name="test",
        source_url="https://example.com",
        source_tier=tier,
        fact_type=FactType.ESTIMATE,
        confidence=0.8,
    )


def test_no_data_at_all_yields_zero_low_confidence() -> None:
    confidence, level = compute_confidence(0.0, [], 0, _CONFIG)
    assert confidence == 0.0
    assert level == ConfidenceLevel.LOW


def test_official_tier_features_yield_higher_confidence_than_broker() -> None:
    official_conf, _ = compute_confidence(1.0, [_feature(SourceTier.OFFICIAL)], 0, _CONFIG)
    broker_conf, _ = compute_confidence(1.0, [_feature(SourceTier.BROKER)], 0, _CONFIG)
    assert official_conf > broker_conf


def test_missing_critical_data_reduces_confidence_but_is_capped() -> None:
    baseline, _ = compute_confidence(1.0, [_feature(SourceTier.OFFICIAL)], 0, _CONFIG)
    with_many_missing, _ = compute_confidence(1.0, [_feature(SourceTier.OFFICIAL)], 50, _CONFIG)
    assert with_many_missing < baseline
    # penalty is capped at 0.20 - a huge missing count shouldn't wipe confidence to 0 when
    # coverage/tier signals are otherwise strong.
    assert with_many_missing >= baseline - 0.20 - 1e-9


def test_special_category_only_contributions_use_neutral_tier_ratio() -> None:
    # price_supply_demand/macro_liquidity 등은 개별 Feature 출처 정보가 없다 (contributing_features
    # 리스트가 비어 있음) - 이 경우 coverage가 있으면 confidence가 0으로 깔리면 안 된다.
    confidence, level = compute_confidence(0.9, [], 0, _CONFIG)
    assert confidence > 0.0


def test_thresholds_map_to_levels() -> None:
    _, low_level = compute_confidence(0.1, [_feature(SourceTier.SOCIAL)], 0, _CONFIG)
    assert low_level == ConfidenceLevel.LOW
    _, high_level = compute_confidence(
        1.0, [_feature(SourceTier.OFFICIAL) for _ in range(5)], 0, _CONFIG
    )
    assert high_level == ConfidenceLevel.HIGH

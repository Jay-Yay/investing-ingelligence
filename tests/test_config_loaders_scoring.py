from pathlib import Path

from investor_intel.config.loaders import (
    load_global_scoring_yaml,
    load_scoring_universe_yaml,
    load_sector_scoring_yaml,
)

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config" / "scoring"


def test_universe_yaml_loads_registered_tickers() -> None:
    universe = load_scoring_universe_yaml(_CONFIG_DIR / "universe.yaml")
    tickers = {t.ticker for t in universe.tickers}
    assert "000660.KS" in tickers
    assert "005930.KS" in tickers


def test_universe_yaml_has_no_position_sizing_fields() -> None:
    # 스코어링 대상 레지스트리에는 average_cost/quantity가 없어야 한다 - 기업 가치 점수는
    # 매수원가와 무관해야 한다는 원칙을 스키마 수준에서 강제한다.
    universe = load_scoring_universe_yaml(_CONFIG_DIR / "universe.yaml")
    fields = set(type(universe.tickers[0]).model_fields.keys())
    assert "average_cost" not in fields
    assert "quantity" not in fields


def test_global_scoring_category_weights_sum_to_100() -> None:
    config = load_global_scoring_yaml(_CONFIG_DIR / "global_scoring.yaml")
    assert sum(config.category_weights.values()) == 100.0


def test_sector_memory_category_weights_sum_to_100() -> None:
    config = load_sector_scoring_yaml(_CONFIG_DIR / "sector_memory.yaml")
    assert sum(config.category_weights.values()) == 100.0


def test_sector_memory_every_listed_feature_has_a_metric_spec() -> None:
    config = load_sector_scoring_yaml(_CONFIG_DIR / "sector_memory.yaml")
    all_metrics = {m for metrics in config.features.values() for m in metrics}
    for ticker_overlay in config.tickers.values():
        all_metrics.update(ticker_overlay.extra_features)
    missing = all_metrics - set(config.metric_specs.keys())
    assert missing == set()


def test_hysteresis_thresholds_are_monotonically_ordered() -> None:
    config = load_global_scoring_yaml(_CONFIG_DIR / "global_scoring.yaml")
    h = config.hysteresis
    assert h.entry_new_buy > h.maintain_buy > h.reduce_review > h.sell_review

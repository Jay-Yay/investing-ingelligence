from datetime import date

from investor_intel.scoring.models import Citation
from investor_intel.scoring.price_supply_demand import (
    PriceSupplyDemandMetrics,
    build_price_supply_demand_rationale,
)

_METRICS = PriceSupplyDemandMetrics(
    as_of=date(2026, 8, 2), close=61200.0, ma20=65000.0, ma60=68000.0, ma120=70000.0,
    ma200=72400.0, ma20_slope_5d=-500.0, pct_below_52w_high=-42.9, return_5d=1.0,
    return_20d=-3.0, rs_20d_vs_benchmark=-6.1, rs_60d_vs_benchmark=-9.0,
    volume_change_ratio_20d=1.1, volatility_20d_pct=2.5, max_drawdown_1y_pct=-45.0,
)


def test_rationale_mentions_close_and_moving_average_position() -> None:
    rationale, citations = build_price_supply_demand_rationale(_METRICS, "005930.KS")
    assert "61,200" in rationale
    assert "아래에 위치" in rationale  # close < ma200
    assert citations == [
        Citation(label="Yahoo Finance", url="https://finance.yahoo.com/quote/005930.KS")
    ]


def test_rationale_does_not_use_scientific_notation_for_large_prices() -> None:
    rationale, _ = build_price_supply_demand_rationale(_METRICS, "005930.KS")
    assert "e+" not in rationale

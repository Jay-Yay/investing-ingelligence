from datetime import UTC, date, datetime

import pytest

from investor_intel.market_data.provider import PriceBar, Quote


def test_quote_requires_timezone_aware_as_of() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Quote(symbol="NBIS", price=42.0, currency="USD", as_of=datetime(2024, 5, 1))


def test_quote_valid_construction() -> None:
    quote = Quote(symbol="NBIS", price=42.0, currency="USD", as_of=datetime(2024, 5, 1, tzinfo=UTC))
    assert quote.symbol == "NBIS"
    assert quote.price == 42.0


def test_price_bar_construction() -> None:
    bar = PriceBar(
        date=date(2024, 5, 1), open=10.0, high=12.0, low=9.5, close=11.0, volume=1000.0
    )
    assert bar.close == 11.0

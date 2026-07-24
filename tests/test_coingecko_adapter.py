from datetime import UTC, datetime

import httpx
import pytest
import respx
from freezegun import freeze_time

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.market_data.coingecko_adapter import CoinGeckoAdapter, CoinGeckoError


@respx.mock
@freeze_time("2024-05-02T12:00:00+00:00")
def test_get_quote_parses_simple_price_response() -> None:
    respx.get(
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
    ).mock(return_value=httpx.Response(200, json={"bitcoin": {"usd": 65000.12}}))
    adapter = CoinGeckoAdapter(SimpleHttpClient())
    quote = adapter.get_quote("bitcoin")

    assert quote.symbol == "bitcoin"
    assert quote.price == 65000.12
    assert quote.currency == "USD"
    assert quote.as_of == datetime(2024, 5, 2, 12, 0, tzinfo=UTC)


@respx.mock
def test_get_price_history_maps_ohlc_with_zero_volume() -> None:
    respx.get(
        "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc?vs_currency=usd&days=7"
    ).mock(
        return_value=httpx.Response(
            200,
            json=[
                [1714521600000, 60000.0, 61000.0, 59500.0, 60800.0],
                [1714608000000, 60800.0, 65500.0, 60500.0, 65000.12],
            ],
        )
    )
    adapter = CoinGeckoAdapter(SimpleHttpClient())
    bars = adapter.get_price_history("bitcoin", days=7)

    assert len(bars) == 2
    assert bars[-1].close == 65000.12
    assert bars[-1].volume == 0.0


@respx.mock
def test_quote_for_unknown_coin_id_raises() -> None:
    respx.get(
        "https://api.coingecko.com/api/v3/simple/price?ids=notacoin&vs_currencies=usd"
    ).mock(return_value=httpx.Response(200, json={}))
    adapter = CoinGeckoAdapter(SimpleHttpClient())
    with pytest.raises(CoinGeckoError):
        adapter.get_quote("notacoin")

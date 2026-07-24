from __future__ import annotations

from datetime import UTC, datetime

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.market_data.provider import PriceBar, Quote

_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
_OHLC_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"


class CoinGeckoError(Exception):
    pass


class CoinGeckoAdapter:
    def __init__(self, client: SimpleHttpClient, vs_currency: str = "usd") -> None:
        self._client = client
        self._vs_currency = vs_currency

    def get_quote(self, coin_id: str) -> Quote:
        url = f"{_SIMPLE_PRICE_URL}?ids={coin_id}&vs_currencies={self._vs_currency}"
        response = self._client.get_json(url)
        entry = response.get(coin_id)
        if not entry or self._vs_currency not in entry:
            raise CoinGeckoError(f"CoinGecko returned no price for coin id {coin_id!r}")
        return Quote(
            symbol=coin_id,
            price=entry[self._vs_currency],
            currency=self._vs_currency.upper(),
            as_of=datetime.now(UTC),
        )

    def get_price_history(self, coin_id: str, days: int) -> list[PriceBar]:
        url = (
            f"{_OHLC_URL.format(coin_id=coin_id)}"
            f"?vs_currency={self._vs_currency}&days={days}"
        )
        response = self._client.get_json(url)
        if not isinstance(response, list):
            raise CoinGeckoError(f"CoinGecko returned an unexpected OHLC response for {coin_id!r}")

        return [
            PriceBar(
                date=datetime.fromtimestamp(ts_ms / 1000, tz=UTC).date(),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=0.0,
            )
            for ts_ms, open_, high, low, close in response
        ]

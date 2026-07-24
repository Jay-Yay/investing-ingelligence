from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.market_data.provider import PriceBar, Quote

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


class YahooFinanceError(Exception):
    pass


class YahooFinanceAdapter:
    def __init__(self, client: SimpleHttpClient) -> None:
        self._client = client

    def _fetch_chart(self, symbol: str, query: str) -> dict[str, Any]:
        response = self._client.get_json(f"{_CHART_URL.format(symbol=symbol)}?{query}")
        chart = response.get("chart", {})
        if chart.get("error"):
            raise YahooFinanceError(f"Yahoo Finance error for {symbol}: {chart['error']}")
        results = chart.get("result") or []
        if not results:
            raise YahooFinanceError(f"Yahoo Finance returned no data for {symbol}")
        return results[0]

    def get_quote(self, symbol: str) -> Quote:
        result = self._fetch_chart(symbol, "interval=1d&range=1d")
        meta = result["meta"]
        return Quote(
            symbol=symbol,
            price=meta["regularMarketPrice"],
            currency=meta["currency"],
            as_of=datetime.fromtimestamp(meta["regularMarketTime"], tz=UTC),
        )

    def get_price_history(self, symbol: str, days: int) -> list[PriceBar]:
        now = datetime.now(UTC)
        period2 = int(now.timestamp())
        period1 = int((now - timedelta(days=days)).timestamp())
        result = self._fetch_chart(symbol, f"period1={period1}&period2={period2}&interval=1d")

        timestamps = result.get("timestamp", [])
        quote = result["indicators"]["quote"][0]

        bars: list[PriceBar] = []
        for i, ts in enumerate(timestamps):
            values = (
                quote["open"][i],
                quote["high"][i],
                quote["low"][i],
                quote["close"][i],
            )
            if None in values:
                continue
            volume = quote["volume"][i]
            bars.append(
                PriceBar(
                    date=datetime.fromtimestamp(ts, tz=UTC).date(),
                    open=values[0],
                    high=values[1],
                    low=values[2],
                    close=values[3],
                    volume=volume or 0.0,
                )
            )
        return bars

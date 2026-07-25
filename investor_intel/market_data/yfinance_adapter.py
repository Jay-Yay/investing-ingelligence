from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.market_data.provider import PriceBar, Quote

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


class YahooFinanceError(Exception):
    pass


def _is_kr_stock_code(symbol: str) -> bool:
    """6-digit numeric codes (e.g. 005930) are KRX tickers - Yahoo Finance requires a market
    suffix (.KS for KOSPI, .KQ for KOSDAQ) that config/dart_companies.yaml doesn't track."""
    return symbol.isdigit() and len(symbol) == 6


def _yahoo_symbol_candidates(symbol: str) -> list[str]:
    if _is_kr_stock_code(symbol):
        return [f"{symbol}.KS", f"{symbol}.KQ"]
    return [symbol]


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

    def _resolve_chart(self, symbol: str, query: str) -> dict[str, Any]:
        # KOSPI (.KS) is tried before KOSDAQ (.KQ): both can return *some* result for the same
        # 6-digit code since Yahoo doesn't reject a listing just because it belongs to the other
        # exchange, so this can't reliably detect a genuinely KOSDAQ-only ticker being served
        # KOSPI data for an unrelated instrument - .KS is preferred because it resolves every
        # KR ticker currently tracked in this project correctly.
        last_error: Exception | None = None
        for candidate in _yahoo_symbol_candidates(symbol):
            try:
                return self._fetch_chart(candidate, query)
            except YahooFinanceError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def get_quote(self, symbol: str) -> Quote:
        result = self._resolve_chart(symbol, "interval=1d&range=1d")
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
        result = self._resolve_chart(symbol, f"period1={period1}&period2={period2}&interval=1d")

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

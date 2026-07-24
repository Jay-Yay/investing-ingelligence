from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.market_data.yfinance_adapter import YahooFinanceAdapter, YahooFinanceError

FIXTURES = Path(__file__).parent / "fixtures" / "market_data"


@respx.mock
def test_get_quote_parses_meta_fields() -> None:
    respx.get("https://query1.finance.yahoo.com/v8/finance/chart/NBIS?interval=1d&range=1d").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_chart_quote.json").read_text(encoding="utf-8")
        )
    )
    adapter = YahooFinanceAdapter(SimpleHttpClient())
    quote = adapter.get_quote("NBIS")

    assert quote.symbol == "NBIS"
    assert quote.price == 42.5
    assert quote.currency == "USD"
    assert quote.as_of == datetime.fromtimestamp(1714608000, tz=UTC)


@respx.mock
@freeze_time("2024-05-02")
def test_get_price_history_maps_ohlcv_arrays() -> None:
    now = datetime.now(UTC)
    period2 = int(now.timestamp())
    period1 = int((now - timedelta(days=3)).timestamp())
    respx.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/NBIS"
        f"?period1={period1}&period2={period2}&interval=1d"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_chart_history.json").read_text(encoding="utf-8")
        )
    )
    adapter = YahooFinanceAdapter(SimpleHttpClient())
    bars = adapter.get_price_history("NBIS", days=3)

    assert len(bars) == 3
    last = bars[-1]
    assert last.close == 42.5
    assert last.volume == 1200000


@respx.mock
def test_error_response_raises() -> None:
    respx.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/BADSYM?interval=1d&range=1d"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_chart_error.json").read_text(encoding="utf-8")
        )
    )
    adapter = YahooFinanceAdapter(SimpleHttpClient())
    try:
        adapter.get_quote("BADSYM")
        raise AssertionError("expected YahooFinanceError")
    except YahooFinanceError:
        pass

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


@respx.mock
def test_get_quote_tries_kospi_suffix_for_six_digit_kr_codes() -> None:
    route = respx.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/005930.KS?interval=1d&range=1d"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_chart_quote.json").read_text(encoding="utf-8")
        )
    )
    adapter = YahooFinanceAdapter(SimpleHttpClient())

    quote = adapter.get_quote("005930")

    assert route.call_count == 1
    # the raw KR code is preserved on the Quote so callers (e.g. portfolio.yaml matching)
    # don't need to know which exchange suffix resolved it
    assert quote.symbol == "005930"
    assert quote.price == 42.5


@respx.mock
def test_get_quote_falls_back_to_kosdaq_suffix_when_kospi_not_found() -> None:
    respx.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/483650.KS?interval=1d&range=1d"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_chart_error.json").read_text(encoding="utf-8")
        )
    )
    respx.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/483650.KQ?interval=1d&range=1d"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_chart_quote.json").read_text(encoding="utf-8")
        )
    )
    adapter = YahooFinanceAdapter(SimpleHttpClient())

    quote = adapter.get_quote("483650")

    assert quote.symbol == "483650"
    assert quote.price == 42.5


@respx.mock
def test_get_quote_raises_when_both_kr_suffixes_fail() -> None:
    respx.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/000000.KS?interval=1d&range=1d"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_chart_error.json").read_text(encoding="utf-8")
        )
    )
    respx.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/000000.KQ?interval=1d&range=1d"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_chart_error.json").read_text(encoding="utf-8")
        )
    )
    adapter = YahooFinanceAdapter(SimpleHttpClient())
    try:
        adapter.get_quote("000000")
        raise AssertionError("expected YahooFinanceError")
    except YahooFinanceError:
        pass


@respx.mock
def test_get_quote_leaves_non_kr_symbols_unsuffixed() -> None:
    route = respx.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/NBIS?interval=1d&range=1d"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_chart_quote.json").read_text(encoding="utf-8")
        )
    )
    YahooFinanceAdapter(SimpleHttpClient()).get_quote("NBIS")
    assert route.call_count == 1

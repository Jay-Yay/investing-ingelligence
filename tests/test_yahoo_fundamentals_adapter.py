import time
from datetime import date
from pathlib import Path

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.market_data.yahoo_fundamentals_adapter import (
    YahooFundamentalsAdapter,
    YahooFundamentalsError,
)

FIXTURES = Path(__file__).parent / "fixtures" / "market_data"

_CRUMB = "test-crumb-abc"

_TYPES = ",".join(
    [
        "quarterlyTotalRevenue",
        "quarterlyOperatingIncome",
        "quarterlyNetIncome",
        "quarterlyOperatingCashFlow",
        "quarterlyCapitalExpenditure",
        "quarterlyCashAndCashEquivalents",
        "quarterlyCurrentAssets",
        "quarterlyCurrentLiabilities",
        "quarterlyTotalDebt",
        "quarterlyStockholdersEquity",
    ]
)


def _mock_crumb() -> None:
    respx.get("https://fc.yahoo.com").mock(return_value=httpx.Response(404))
    respx.get("https://query2.finance.yahoo.com/v1/test/getcrumb").mock(
        return_value=httpx.Response(200, text=_CRUMB)
    )


@respx.mock
def test_get_market_cap_parses_price_module() -> None:
    _mock_crumb()
    respx.get(
        f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/NBIS"
        f"?modules=price&crumb={_CRUMB}"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_quote_summary_price.json").read_text(encoding="utf-8")
        )
    )
    adapter = YahooFundamentalsAdapter(SimpleHttpClient())

    market_cap, currency = adapter.get_market_cap("NBIS")

    assert market_cap == 47_674_466_304.0
    assert currency == "USD"


@respx.mock
def test_get_market_cap_tries_kosdaq_suffix_when_kospi_empty() -> None:
    _mock_crumb()
    respx.get(
        f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/483650.KS"
        f"?modules=price&crumb={_CRUMB}"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_quote_summary_empty.json").read_text(encoding="utf-8")
        )
    )
    respx.get(
        f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/483650.KQ"
        f"?modules=price&crumb={_CRUMB}"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_quote_summary_price.json").read_text(encoding="utf-8")
        )
    )
    adapter = YahooFundamentalsAdapter(SimpleHttpClient())

    market_cap, currency = adapter.get_market_cap("483650")

    assert market_cap == 47_674_466_304.0
    assert currency == "USD"


@respx.mock
def test_get_market_cap_raises_when_all_candidates_fail() -> None:
    _mock_crumb()
    respx.get(
        f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/000000.KS"
        f"?modules=price&crumb={_CRUMB}"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_quote_summary_empty.json").read_text(encoding="utf-8")
        )
    )
    respx.get(
        f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/000000.KQ"
        f"?modules=price&crumb={_CRUMB}"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_quote_summary_empty.json").read_text(encoding="utf-8")
        )
    )
    adapter = YahooFundamentalsAdapter(SimpleHttpClient())
    try:
        adapter.get_market_cap("000000")
        raise AssertionError("expected YahooFundamentalsError")
    except YahooFundamentalsError:
        pass


@respx.mock
@freeze_time("2026-07-26")
def test_get_quarterly_fundamentals_parses_timeseries() -> None:
    _mock_crumb()
    now = int(time.time())
    period1 = now - 3 * 365 * 24 * 3600
    respx.get(
        f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/NBIS"
        f"?symbol=NBIS&type={_TYPES}&period1={period1}&period2={now}&crumb={_CRUMB}"
    ).mock(
        return_value=httpx.Response(
            200,
            text=(FIXTURES / "yahoo_fundamentals_timeseries.json").read_text(encoding="utf-8"),
        )
    )
    adapter = YahooFundamentalsAdapter(SimpleHttpClient())

    fundamentals = adapter.get_quarterly_fundamentals("NBIS")

    assert fundamentals.symbol == "NBIS"
    assert [p.value for p in fundamentals.revenue] == [
        100_000_000.0,
        120_000_000.0,
        150_000_000.0,
        200_000_000.0,
        300_000_000.0,
    ]
    assert fundamentals.revenue[-1].as_of_date == date(2026, 3, 31)
    assert fundamentals.capital_expenditure[-1].value == -247_000_000.0
    assert fundamentals.cash_and_equivalents[-1].value == 929_820_000.0
    assert len(fundamentals.current_assets) == 1


@respx.mock
@freeze_time("2026-07-26")
def test_get_quarterly_fundamentals_reuses_crumb_across_calls() -> None:
    _mock_crumb()
    now = int(time.time())
    period1 = now - 3 * 365 * 24 * 3600
    route = respx.get(
        f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/NBIS"
        f"?symbol=NBIS&type={_TYPES}&period1={period1}&period2={now}&crumb={_CRUMB}"
    ).mock(
        return_value=httpx.Response(
            200,
            text=(FIXTURES / "yahoo_fundamentals_timeseries.json").read_text(encoding="utf-8"),
        )
    )
    price_route = respx.get(
        f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/NBIS"
        f"?modules=price&crumb={_CRUMB}"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "yahoo_quote_summary_price.json").read_text(encoding="utf-8")
        )
    )
    crumb_route = respx.get(
        "https://query2.finance.yahoo.com/v1/test/getcrumb"
    ).mock(return_value=httpx.Response(200, text=_CRUMB))

    adapter = YahooFundamentalsAdapter(SimpleHttpClient())
    adapter.get_quarterly_fundamentals("NBIS")
    adapter.get_market_cap("NBIS")

    assert route.call_count == 1
    assert price_route.call_count == 1
    assert crumb_route.call_count == 1  # 두 번째 호출부터는 캐시된 crumb을 재사용한다

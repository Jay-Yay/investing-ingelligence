import time
from datetime import UTC, datetime

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.market_data.yahoo_fundamentals_adapter import YahooFundamentalsAdapter
from investor_intel.regime.collectors import ai_semiconductor_demand
from investor_intel.regime.models import IndicatorId, IndicatorStatus

_CRUMB = "test-crumb"
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
_FROZEN_NOW = "2026-08-01"


def _mock_crumb() -> None:
    respx.get("https://fc.yahoo.com").mock(return_value=httpx.Response(404))
    respx.get("https://query2.finance.yahoo.com/v1/test/getcrumb").mock(
        return_value=httpx.Response(200, text=_CRUMB)
    )


def _quarter_dates(n: int) -> list[str]:
    dates = []
    year, month_idx = 2024, 0
    months = ["03-31", "06-30", "09-30", "12-31"]
    for _ in range(n):
        dates.append(f"{year}-{months[month_idx]}")
        month_idx += 1
        if month_idx == 4:
            month_idx = 0
            year += 1
    return dates


def _revenue_payload(symbol: str, revenue: list[float]) -> dict:
    dates = _quarter_dates(len(revenue))
    return {
        "timeseries": {
            "error": None,
            "result": [
                {
                    "meta": {"symbol": [symbol], "type": ["quarterlyTotalRevenue"]},
                    "timestamp": list(range(len(revenue))),
                    "quarterlyTotalRevenue": [
                        {
                            "dataId": 1,
                            "asOfDate": d,
                            "periodType": "3M",
                            "currencyCode": "USD",
                            "reportedValue": {"raw": v, "fmt": str(v)},
                        }
                        for d, v in zip(dates, revenue, strict=True)
                    ],
                }
            ],
        }
    }


def _mock_fundamentals(symbol: str, revenue: list[float]) -> None:
    now = int(time.time())
    period1 = now - ai_semiconductor_demand._LOOKBACK_DAYS * 24 * 3600
    respx.get(
        f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}"
        f"?symbol={symbol}&type={_TYPES}&period1={period1}&period2={now}&crumb={_CRUMB}"
    ).mock(return_value=httpx.Response(200, json=_revenue_payload(symbol, revenue)))


@freeze_time(_FROZEN_NOW)
@respx.mock
def test_collect_computes_revenue_growth() -> None:
    _mock_crumb()
    revenue = [100_000_000.0 + i * 20_000_000.0 for i in range(9)]  # 꾸준히 성장
    for ticker in ai_semiconductor_demand._TICKERS:
        _mock_fundamentals(ticker, revenue)

    adapter = YahooFundamentalsAdapter(SimpleHttpClient())
    obs = ai_semiconductor_demand.collect(adapter, datetime.now(UTC))

    assert obs.status == IndicatorStatus.OK
    assert obs.indicator_id == IndicatorId.AI_SEMICONDUCTOR_DEMAND
    assert obs.value is not None and obs.value > 0
    assert obs.details["sample_size"] == len(ai_semiconductor_demand._TICKERS)
    for ticker in ai_semiconductor_demand._TICKERS:
        company = obs.details["companies"][ticker]
        assert company["revenue_growth_yoy_pct"] > 0
    assert obs.details["cadence_note"]
    assert obs.details["datacenter_segment_revenue_growth_yoy"] is None


@freeze_time(_FROZEN_NOW)
@respx.mock
def test_collect_returns_unavailable_when_all_companies_fail() -> None:
    _mock_crumb()
    now = int(time.time())
    period1 = now - ai_semiconductor_demand._LOOKBACK_DAYS * 24 * 3600
    for ticker in ai_semiconductor_demand._TICKERS:
        respx.get(
            f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{ticker}"
            f"?symbol={ticker}&type={_TYPES}&period1={period1}&period2={now}&crumb={_CRUMB}"
        ).mock(return_value=httpx.Response(404))

    adapter = YahooFundamentalsAdapter(SimpleHttpClient())
    obs = ai_semiconductor_demand.collect(adapter, datetime.now(UTC))

    assert obs.status == IndicatorStatus.UNAVAILABLE

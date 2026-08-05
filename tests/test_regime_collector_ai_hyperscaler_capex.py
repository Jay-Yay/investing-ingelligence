import time
from datetime import UTC, datetime

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.market_data.yahoo_fundamentals_adapter import YahooFundamentalsAdapter
from investor_intel.regime.collectors import ai_hyperscaler_capex
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
    # 분기말(3/31,6/30,9/30,12/31) 근사 - 실제 정확한 말일 여부는 계산 로직과 무관하다
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


def _fundamentals_payload(symbol: str, capex: list[float], ocf: list[float]) -> dict:
    dates = _quarter_dates(len(capex))
    timestamps = list(range(len(capex)))

    def _series(concept: str, values: list[float]) -> dict:
        return {
            "meta": {"symbol": [symbol], "type": [concept]},
            "timestamp": timestamps,
            concept: [
                {
                    "dataId": 1,
                    "asOfDate": d,
                    "periodType": "3M",
                    "currencyCode": "USD",
                    "reportedValue": {"raw": v, "fmt": str(v)},
                }
                for d, v in zip(dates, values, strict=True)
            ],
        }

    return {
        "timeseries": {
            "error": None,
            "result": [
                _series("quarterlyCapitalExpenditure", capex),
                _series("quarterlyOperatingCashFlow", ocf),
            ],
        }
    }


def _mock_fundamentals(symbol: str, capex: list[float], ocf: list[float]) -> None:
    now = int(time.time())
    period1 = now - ai_hyperscaler_capex._LOOKBACK_DAYS * 24 * 3600
    respx.get(
        f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}"
        f"?symbol={symbol}&type={_TYPES}&period1={period1}&period2={now}&crumb={_CRUMB}"
    ).mock(return_value=httpx.Response(200, json=_fundamentals_payload(symbol, capex, ocf)))


@freeze_time(_FROZEN_NOW)
@respx.mock
def test_collect_computes_capex_intensity_and_growth() -> None:
    _mock_crumb()
    # 9분기: capex는 꾸준히 증가(성장), ocf는 일정 - capex_intensity가 시간에 따라 커진다
    capex = [-(50_000_000.0 + i * 5_000_000.0) for i in range(9)]
    ocf = [200_000_000.0] * 9
    for ticker in ai_hyperscaler_capex._TICKERS:
        _mock_fundamentals(ticker, capex, ocf)

    adapter = YahooFundamentalsAdapter(SimpleHttpClient())
    obs = ai_hyperscaler_capex.collect(adapter, datetime.now(UTC))

    assert obs.status == IndicatorStatus.OK
    assert obs.indicator_id == IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY
    assert obs.value is not None and obs.value > 0
    assert obs.details["sample_size"] == len(ai_hyperscaler_capex._TICKERS)
    for ticker in ai_hyperscaler_capex._TICKERS:
        company = obs.details["companies"][ticker]
        assert company["capex_intensity"] is not None
        assert company["capex_growth_yoy_pct"] is not None
        assert company["capex_growth_yoy_pct"] > 0  # capex가 늘어나는 추세이므로 양수
    # cloud/AI 매출 관련 필드는 Phase 2b(LLM) 전까지 항상 None
    assert obs.details["cloud_ai_revenue_growth_yoy"] is None
    assert obs.details["monetization_gap"] is None


@freeze_time(_FROZEN_NOW)
@respx.mock
def test_collect_tolerates_partial_company_failures() -> None:
    _mock_crumb()
    capex = [-(50_000_000.0 + i * 5_000_000.0) for i in range(9)]
    ocf = [200_000_000.0] * 9
    tickers = ai_hyperscaler_capex._TICKERS
    # 첫 종목만 실패(404) 시키고 나머지는 정상 응답
    now = int(time.time())
    period1 = now - ai_hyperscaler_capex._LOOKBACK_DAYS * 24 * 3600
    respx.get(
        f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{tickers[0]}"
        f"?symbol={tickers[0]}&type={_TYPES}&period1={period1}&period2={now}&crumb={_CRUMB}"
    ).mock(return_value=httpx.Response(404))
    for ticker in tickers[1:]:
        _mock_fundamentals(ticker, capex, ocf)

    adapter = YahooFundamentalsAdapter(SimpleHttpClient())
    obs = ai_hyperscaler_capex.collect(adapter, datetime.now(UTC))

    assert obs.status == IndicatorStatus.OK
    assert obs.details["sample_size"] == len(tickers) - 1
    assert tickers[0] not in obs.details["companies"]


@freeze_time(_FROZEN_NOW)
@respx.mock
def test_collect_returns_unavailable_when_all_companies_fail() -> None:
    _mock_crumb()
    now = int(time.time())
    period1 = now - ai_hyperscaler_capex._LOOKBACK_DAYS * 24 * 3600
    for ticker in ai_hyperscaler_capex._TICKERS:
        respx.get(
            f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{ticker}"
            f"?symbol={ticker}&type={_TYPES}&period1={period1}&period2={now}&crumb={_CRUMB}"
        ).mock(return_value=httpx.Response(404))

    adapter = YahooFundamentalsAdapter(SimpleHttpClient())
    obs = ai_hyperscaler_capex.collect(adapter, datetime.now(UTC))

    assert obs.status == IndicatorStatus.UNAVAILABLE

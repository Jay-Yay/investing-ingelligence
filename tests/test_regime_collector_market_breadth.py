from datetime import UTC, datetime, timedelta

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.market_data.yfinance_adapter import YahooFinanceAdapter
from investor_intel.regime.collectors import market_breadth
from investor_intel.regime.models import IndicatorId, IndicatorStatus

_FROZEN_NOW = "2026-01-15T09:00:00+00:00"

# 위키피디아 "List of S&P 500 companies" 표(id="constituents")를 흉내낸 synthetic HTML.
# BRK.B는 실제 표기(점 표기)를 그대로 넣어 Yahoo 호환 하이픈 변환(BRK-B)을 검증한다.
_WIKI_HTML = """
<html><body>
<table class="wikitable sortable" id="constituents">
<tbody>
<tr><th>Symbol</th><th>Security</th><th>GICS Sector</th></tr>
<tr><td><a href="#">AAA</a></td><td>Company A</td><td>Technology</td></tr>
<tr><td><a href="#">BBB</a></td><td>Company B</td><td>Technology</td></tr>
<tr><td><a href="#">BRK.B</a></td><td>Company C</td><td>Financials</td></tr>
</tbody>
</table>
<table id="unrelated"><tr><td>should not be parsed</td></tr></table>
</body></html>
"""


def _chart_json(closes: list[float], start_ts: int) -> dict:
    n = len(closes)
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [start_ts + i * 86400 for i in range(n)],
                    "indicators": {
                        "quote": [
                            {
                                "open": closes,
                                "high": closes,
                                "low": closes,
                                "close": closes,
                                "volume": [1000] * n,
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def _mock_price_history(symbol: str, days: int, closes: list[float], now: datetime) -> None:
    period2 = int(now.timestamp())
    period1 = int((now - timedelta(days=days)).timestamp())
    respx.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={period1}&period2={period2}&interval=1d"
    ).mock(return_value=httpx.Response(200, json=_chart_json(closes, period1)))


@freeze_time(_FROZEN_NOW)
@respx.mock
def test_fetch_constituents_converts_dot_tickers_to_hyphen_form() -> None:
    respx.get(market_breadth._WIKIPEDIA_SP500_URL).mock(
        return_value=httpx.Response(200, text=_WIKI_HTML)
    )
    tickers = market_breadth.fetch_constituents(SimpleHttpClient())
    assert tickers == ["AAA", "BBB", "BRK-B"]


@freeze_time(_FROZEN_NOW)
@respx.mock
def test_collect_computes_breadth_from_constituent_prices() -> None:
    now = datetime.now(UTC)
    respx.get(market_breadth._WIKIPEDIA_SP500_URL).mock(
        return_value=httpx.Response(200, text=_WIKI_HTML)
    )
    closes_60_days = [100.0 + i * 0.1 for i in range(60)]  # 상승 추세 -> 50일선 위
    _mock_price_history("AAA", 400, closes_60_days, now)
    _mock_price_history("BBB", 400, closes_60_days, now)
    _mock_price_history("RSP", 120, [50.0 + i * 0.05 for i in range(60)], now)
    _mock_price_history("SPY", 120, [400.0 + i * 0.2 for i in range(60)], now)

    yahoo = YahooFinanceAdapter(SimpleHttpClient())
    constituents_client = SimpleHttpClient()
    obs = market_breadth.collect(yahoo, constituents_client, now, max_constituents=2)

    assert obs.status == IndicatorStatus.OK
    assert obs.indicator_id == IndicatorId.MARKET_BREADTH
    assert obs.details["sample_size"] == 2
    assert obs.details["pct_above_50dma"] == 100.0
    # 60일치 데이터만 있어 200일선 판정은 불가능(None) -> 두 종목 모두 above_200 카운트에서 빠짐
    assert obs.details["pct_above_200dma"] == 0.0


@freeze_time(_FROZEN_NOW)
@respx.mock
def test_collect_returns_unavailable_when_constituents_table_missing() -> None:
    respx.get(market_breadth._WIKIPEDIA_SP500_URL).mock(
        return_value=httpx.Response(200, text="<html><body>no table here</body></html>")
    )
    yahoo = YahooFinanceAdapter(SimpleHttpClient())
    obs = market_breadth.collect(yahoo, SimpleHttpClient(), datetime.now(UTC))
    assert obs.status == IndicatorStatus.UNAVAILABLE

from datetime import UTC, datetime, timedelta

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.market_data.yfinance_adapter import YahooFinanceAdapter
from investor_intel.regime.collectors import vix_term_structure
from investor_intel.regime.models import IndicatorId, IndicatorStatus

_FROZEN_NOW = "2026-01-15T09:00:00+00:00"


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


def _mock(symbol: str, days: int, closes: list[float], now: datetime) -> None:
    period2 = int(now.timestamp())
    period1 = int((now - timedelta(days=days)).timestamp())
    respx.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={period1}&period2={period2}&interval=1d"
    ).mock(return_value=httpx.Response(200, json=_chart_json(closes, period1)))


@freeze_time(_FROZEN_NOW)
@respx.mock
def test_backwardation_signal_when_vix_above_vix3m() -> None:
    now = datetime.now(UTC)
    _mock("^VIX", 365 * 5, [15.0] * 20 + [25.0], now)
    _mock("^VIX3M", 30, [20.0], now)

    yahoo = YahooFinanceAdapter(SimpleHttpClient())
    obs = vix_term_structure.collect(yahoo, now)

    assert obs.status == IndicatorStatus.OK
    assert obs.indicator_id == IndicatorId.VIX_TERM_STRUCTURE
    assert obs.value == round(25.0 / 20.0, 3)
    assert obs.details["backwardation_signal"] is True


@freeze_time(_FROZEN_NOW)
@respx.mock
def test_contango_calm_signal_when_vix_low_and_ratio_low() -> None:
    now = datetime.now(UTC)
    # 21개 값 중 마지막(오늘)이 가장 낮음(=자기 자신 포함 최솟값) -> 5년 백분위가 낮게 나와야 함
    history = list(range(30, 10, -1)) + [10.0]
    _mock("^VIX", 365 * 5, history, now)
    _mock("^VIX3M", 30, [15.0], now)

    yahoo = YahooFinanceAdapter(SimpleHttpClient())
    obs = vix_term_structure.collect(yahoo, now)

    assert obs.details["vix_5y_percentile"] == round(100 / len(history), 1)
    assert obs.details["contango_calm_signal"] is True

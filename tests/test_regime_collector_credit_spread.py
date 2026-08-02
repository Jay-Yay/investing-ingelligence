from datetime import UTC, date, datetime, timedelta

import httpx
import respx

from investor_intel.regime.collectors import credit_spread
from investor_intel.regime.fred_client import FredClient
from investor_intel.regime.models import IndicatorId, IndicatorStatus

_NOW = datetime(2026, 1, 1, 9, tzinfo=UTC)


def _fred_payload(values: list[float | None], start: date) -> dict:
    return {
        "observations": [
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "value": str(v) if v is not None else ".",
            }
            for i, v in enumerate(values)
        ]
    }


@respx.mock
def test_collect_computes_headline_value_and_percentile() -> None:
    # 30개의 낮은 값 뒤에 오늘의 높은 값 하나 - 오늘 값이 최상위 백분위여야 한다
    values = [3.0] * 30 + [8.0]
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(
            200, json=_fred_payload(values, date(2025, 1, 1))
        )
    )
    fred = FredClient("test-key")
    obs = credit_spread.collect(fred, _NOW)

    assert obs.status == IndicatorStatus.OK
    assert obs.indicator_id == IndicatorId.CREDIT_SPREAD_HY_OAS
    assert obs.value == 8.0
    assert obs.details["percentile_10y"] == 100.0
    assert obs.details["cooling_signal"] is True


@respx.mock
def test_collect_skips_missing_dot_values() -> None:
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(
            200,
            json=_fred_payload([3.0, None, 3.1], date(2025, 1, 1)),
        )
    )
    fred = FredClient("test-key")
    obs = credit_spread.collect(fred, _NOW)
    assert obs.value == 3.1


@respx.mock
def test_collect_returns_unavailable_on_http_error(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(500)
    )
    fred = FredClient("test-key")
    obs = credit_spread.collect(fred, _NOW)
    assert obs.status == IndicatorStatus.UNAVAILABLE
    assert obs.value is None

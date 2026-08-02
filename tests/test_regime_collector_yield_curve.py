from datetime import UTC, date, datetime, timedelta

import httpx
import respx

from investor_intel.regime.collectors import yield_curve
from investor_intel.regime.fred_client import FredClient
from investor_intel.regime.models import IndicatorId, IndicatorStatus

_NOW = datetime(2026, 1, 1, 9, tzinfo=UTC)


def _fred_payload(values: list[float], start: date) -> dict:
    return {
        "observations": [
            {"date": (start + timedelta(days=i)).isoformat(), "value": str(v)}
            for i, v in enumerate(values)
        ]
    }


@respx.mock
def test_detects_rapid_normalization_after_recent_inversion() -> None:
    # -0.5(역전) 상태가 30일 지속된 뒤, 60일에 걸쳐 +0.3까지 선형 정상화(80bp, 90일 이내)
    ramp = [-0.5 + i * (0.8 / 59) for i in range(60)]
    values = [-0.5] * 30 + ramp
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=_fred_payload(values, date(2025, 10, 1)))
    )
    obs = yield_curve.collect(FredClient("test-key"), _NOW)

    assert obs.status == IndicatorStatus.OK
    assert obs.indicator_id == IndicatorId.YIELD_CURVE_10Y3M
    assert obs.details["inverted_in_last_12m"] is True
    assert obs.details["normalization_since_trough_bps"] == 80.0
    assert obs.details["rapid_normalization_signal"] is True


@respx.mock
def test_no_inversion_in_last_12_months() -> None:
    values = [0.5] * 90
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=_fred_payload(values, date(2025, 10, 1)))
    )
    obs = yield_curve.collect(FredClient("test-key"), _NOW)
    assert obs.details["inverted_in_last_12m"] is False
    assert obs.details["rapid_normalization_signal"] is False

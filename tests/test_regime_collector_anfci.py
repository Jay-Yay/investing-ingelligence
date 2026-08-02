from datetime import UTC, date, datetime, timedelta

import httpx
import respx

from investor_intel.regime.collectors import anfci
from investor_intel.regime.fred_client import FredClient
from investor_intel.regime.models import IndicatorId, IndicatorStatus

_NOW = datetime(2026, 1, 1, 9, tzinfo=UTC)


def _fred_payload(values: list[float], start: date) -> dict:
    return {
        "observations": [
            {"date": (start + timedelta(weeks=i)).isoformat(), "value": str(v)}
            for i, v in enumerate(values)
        ]
    }


@respx.mock
def test_tightening_signal_when_positive_and_rising() -> None:
    # 13주 전 -0.5에서 현재 +0.5로 상승 - 긴축 신호가 켜져야 한다
    values = [-0.5] * 14 + [0.5]
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=_fred_payload(values, date(2025, 1, 1)))
    )
    obs = anfci.collect(FredClient("test-key"), _NOW)

    assert obs.status == IndicatorStatus.OK
    assert obs.indicator_id == IndicatorId.CHICAGO_FED_ANFCI
    assert obs.value == 0.5
    assert obs.details["tightening_signal"] is True
    assert obs.details["easing_signal"] is False

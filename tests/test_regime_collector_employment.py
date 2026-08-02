from datetime import UTC, date, datetime, timedelta

import httpx
import respx

from investor_intel.regime.collectors import employment
from investor_intel.regime.fred_client import FredClient
from investor_intel.regime.models import IndicatorId, IndicatorStatus

_NOW = datetime(2026, 1, 1, 9, tzinfo=UTC)


def _weekly_payload(values: list[float], start: date) -> dict:
    return {
        "observations": [
            {"date": (start + timedelta(weeks=i)).isoformat(), "value": str(v)}
            for i, v in enumerate(values)
        ]
    }


def _mock_series(series_id: str, values: list[float], start: date) -> None:
    respx.get(
        f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
        "&api_key=test-key&file_type=json&observation_start=1990-01-01"
    ).mock(return_value=httpx.Response(200, json=_weekly_payload(values, start)))


@respx.mock
def test_cooling_signal_when_claims_up_yoy_and_continued_claims_rising() -> None:
    start_year_ago = date(2024, 12, 30)
    # 4주 평균 신규청구: 1년 전 200 -> 오늘 240 (+20% YoY, 15% 기준 초과)
    icsa_values = [200.0] * 53
    ic4wsa_values = [200.0] * 52 + [240.0]
    # 계속 청구도 동반 증가 (+10% YoY)
    ccsa_values = [1800.0] * 52 + [1980.0]
    sahm_values = [0.1] * 53

    _mock_series("ICSA", icsa_values, start_year_ago)
    _mock_series("IC4WSA", ic4wsa_values, start_year_ago)
    _mock_series("CCSA", ccsa_values, start_year_ago)
    _mock_series("SAHMREALTIME", sahm_values, start_year_ago)

    obs = employment.collect(FredClient("test-key"), _NOW)

    assert obs.status == IndicatorStatus.OK
    assert obs.indicator_id == IndicatorId.EMPLOYMENT_COOLING
    assert obs.details["initial_claims_4wma_yoy_pct"] == 20.0
    assert obs.details["cooling_signal"] is True
    assert obs.details["sahm_exceeded_signal"] is False


@respx.mock
def test_sahm_rule_exceeded_forces_cooling_signal_even_if_claims_flat() -> None:
    start_year_ago = date(2024, 12, 30)
    flat = [200.0] * 53
    sahm_values = [0.1] * 52 + [0.6]

    _mock_series("ICSA", flat, start_year_ago)
    _mock_series("IC4WSA", flat, start_year_ago)
    _mock_series("CCSA", flat, start_year_ago)
    _mock_series("SAHMREALTIME", sahm_values, start_year_ago)

    obs = employment.collect(FredClient("test-key"), _NOW)

    assert obs.details["sahm_exceeded_signal"] is True
    assert obs.details["cooling_signal"] is True

from __future__ import annotations

from datetime import date, datetime

from investor_intel.regime.collectors.common import build_observation, unavailable_observation
from investor_intel.regime.fred_client import FredClient, series_url
from investor_intel.regime.models import IndicatorFrequency, IndicatorId, IndicatorObservation
from investor_intel.regime.percentile import compute_changes, compute_percentiles

SERIES_ID = "ANFCI"
INDICATOR_NAME = "Chicago Fed Adjusted National Financial Conditions Index"
SOURCE_NAME = "FRED (Federal Reserve Bank of St. Louis)"
_BACKFILL_START = date(1990, 1, 1)


def collect(fred: FredClient, fetched_at: datetime) -> IndicatorObservation:
    """ANFCI는 주간 지표(FRED 기준 index 값, 0 = 평균적인 금융여건, 양수=긴축/음수=완화).

    details 키: change_4w, change_13w, percentile_5y, tightening_signal, easing_signal.
    """
    try:
        raw = fred.get_observations(SERIES_ID, observation_start=_BACKFILL_START)
    except Exception as exc:  # noqa: BLE001
        return unavailable(fetched_at, str(exc))

    series = sorted((o.observation_date, o.value) for o in raw if o.value is not None)
    if not series:
        return unavailable(fetched_at, "FRED returned no usable observations")

    latest_date, latest_value = series[-1]
    changes = compute_changes(series, [4, 13])
    change_4w, change_13w = changes[4], changes[13]
    percentiles = compute_percentiles(series, latest_date, [5])
    percentile_5y = percentiles[5]

    tightening_signal = bool(latest_value > 0 and change_13w is not None and change_13w > 0)
    easing_signal = bool(latest_value < 0 and change_13w is not None and change_13w < 0)

    return build_observation(
        indicator_id=IndicatorId.CHICAGO_FED_ANFCI,
        indicator_name=INDICATOR_NAME,
        value=latest_value,
        unit="index",
        observation_date=latest_date,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=series_url(SERIES_ID),
        frequency=IndicatorFrequency.WEEKLY,
        details={
            "change_4w": change_4w,
            "change_13w": change_13w,
            "percentile_5y": percentile_5y,
            "tightening_signal": tightening_signal,
            "easing_signal": easing_signal,
        },
    )


def unavailable(fetched_at: datetime, reason: str) -> IndicatorObservation:
    return unavailable_observation(
        indicator_id=IndicatorId.CHICAGO_FED_ANFCI,
        indicator_name=INDICATOR_NAME,
        unit="index",
        frequency=IndicatorFrequency.WEEKLY,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=series_url(SERIES_ID),
        reason=reason,
    )

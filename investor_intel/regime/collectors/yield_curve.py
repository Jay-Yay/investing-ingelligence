from __future__ import annotations

from datetime import date, datetime, timedelta

from investor_intel.regime.collectors.common import build_observation, unavailable_observation
from investor_intel.regime.fred_client import FredClient, series_url
from investor_intel.regime.models import IndicatorFrequency, IndicatorId, IndicatorObservation
from investor_intel.regime.percentile import compute_changes

SERIES_ID = "T10Y3M"
INDICATOR_NAME = "10년물-3개월물 금리차"
SOURCE_NAME = "FRED (Federal Reserve Bank of St. Louis)"
_BACKFILL_START = date(1990, 1, 1)


def _trough_within_window(
    series: list[tuple[date, float]], as_of: date, window_days: int
) -> tuple[date, float] | None:
    cutoff = as_of - timedelta(days=window_days)
    windowed = [(d, v) for d, v in series if cutoff <= d <= as_of]
    if not windowed:
        return None
    return min(windowed, key=lambda p: p[1])


def collect(fred: FredClient, fetched_at: datetime) -> IndicatorObservation:
    """FRED T10Y3M(10Y-3M 금리차, %p). 최근 12개월 내 역전 여부와, 역전됐었다면 그 최저점
    이후 얼마나 정상화됐는지를 함께 계산한다.

    details 키: change_20d_bps, change_63d_bps, inverted_in_last_12m, trough_12m,
    normalization_since_trough_bps, rapid_normalization_signal.
    """
    try:
        raw = fred.get_observations(SERIES_ID, observation_start=_BACKFILL_START)
    except Exception as exc:  # noqa: BLE001
        return unavailable(fetched_at, str(exc))

    series = sorted((o.observation_date, o.value) for o in raw if o.value is not None)
    if not series:
        return unavailable(fetched_at, "FRED returned no usable observations")

    latest_date, latest_value = series[-1]
    changes = compute_changes(series, [20, 63])
    change_20d, change_63d = changes[20], changes[63]

    trough = _trough_within_window(series, latest_date, 365)
    inverted_in_last_12m = trough is not None and trough[1] < 0
    normalization_since_trough_bps = None
    rapid_normalization_signal = False
    if inverted_in_last_12m and trough is not None:
        normalization_since_trough_bps = round((latest_value - trough[1]) * 100, 1)
        days_since_trough = (latest_date - trough[0]).days
        rapid_normalization_signal = bool(
            normalization_since_trough_bps >= 75 and days_since_trough <= 95
        )

    return build_observation(
        indicator_id=IndicatorId.YIELD_CURVE_10Y3M,
        indicator_name=INDICATOR_NAME,
        value=latest_value,
        unit="pct_points",
        observation_date=latest_date,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=series_url(SERIES_ID),
        frequency=IndicatorFrequency.DAILY,
        details={
            "change_20d_bps": None if change_20d is None else round(change_20d * 100, 1),
            "change_63d_bps": None if change_63d is None else round(change_63d * 100, 1),
            "inverted_in_last_12m": inverted_in_last_12m,
            "trough_12m": None if trough is None else trough[1],
            "normalization_since_trough_bps": normalization_since_trough_bps,
            "rapid_normalization_signal": rapid_normalization_signal,
        },
    )


def unavailable(fetched_at: datetime, reason: str) -> IndicatorObservation:
    return unavailable_observation(
        indicator_id=IndicatorId.YIELD_CURVE_10Y3M,
        indicator_name=INDICATOR_NAME,
        unit="pct_points",
        frequency=IndicatorFrequency.DAILY,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=series_url(SERIES_ID),
        reason=reason,
    )

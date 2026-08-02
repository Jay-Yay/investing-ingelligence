from __future__ import annotations

from datetime import date, datetime

from investor_intel.regime.collectors.common import build_observation, unavailable_observation
from investor_intel.regime.fred_client import FredClient, series_url
from investor_intel.regime.models import IndicatorFrequency, IndicatorId, IndicatorObservation
from investor_intel.regime.percentile import (
    change_series,
    compute_changes,
    compute_percentiles,
    values_within_window,
    zscore,
)

SERIES_ID = "BAMLH0A0HYM2"
INDICATOR_NAME = "ICE BofA US High Yield OAS"
SOURCE_NAME = "FRED (Federal Reserve Bank of St. Louis)"
_BACKFILL_START = date(2000, 1, 1)


def collect(fred: FredClient, fetched_at: datetime) -> IndicatorObservation:
    """FRED BAMLH0A0HYM2 전체 시계열(2000년~)을 매번 새로 받아 그 안에서 직접 백분위/변화량을
    계산한다 - FRED가 이미 20년+ 무료 히스토리를 제공하므로 우리 쪽 JSONL 히스토리가 쌓이길
    기다릴 필요가 없다. JSONL에는 오늘 계산된 이 결과 한 줄만 append된다(원천 데이터 자체는
    FRED가 원본이므로 우리가 다시 저장하지 않는다).

    details 키: change_5d_bps, change_20d_bps, percentile_3y, percentile_5y, percentile_10y,
    zscore_5y_20d_change, cooling_signal, overheating_signal.
    """
    try:
        raw = fred.get_observations(SERIES_ID, observation_start=_BACKFILL_START)
    except Exception as exc:  # noqa: BLE001
        return unavailable(fetched_at, str(exc))

    series = sorted((o.observation_date, o.value) for o in raw if o.value is not None)
    if not series:
        return unavailable(fetched_at, "FRED returned no usable observations")

    latest_date, latest_value = series[-1]
    changes = compute_changes(series, [5, 20])
    change_5d, change_20d = changes[5], changes[20]
    percentiles = compute_percentiles(series, latest_date, [3, 5, 10])

    zscore_5y_20d_change = None
    change_20d_ts = change_series(series, 20)
    if change_20d is not None and change_20d_ts:
        window = values_within_window(change_20d_ts, latest_date, 365 * 5)
        zscore_5y_20d_change = zscore(window, change_20d)

    percentile_10y = percentiles[10]
    cooling_signal = bool(
        (percentile_10y is not None and percentile_10y >= 80)
        or (change_20d is not None and change_20d * 100 >= 75)
    )
    overheating_signal = bool(
        percentile_10y is not None and percentile_10y <= 10 and (change_20d or 0) <= 0
    )

    return build_observation(
        indicator_id=IndicatorId.CREDIT_SPREAD_HY_OAS,
        indicator_name=INDICATOR_NAME,
        value=latest_value,
        unit="pct",
        observation_date=latest_date,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=series_url(SERIES_ID),
        frequency=IndicatorFrequency.DAILY,
        details={
            "change_5d_bps": None if change_5d is None else round(change_5d * 100, 1),
            "change_20d_bps": None if change_20d is None else round(change_20d * 100, 1),
            "percentile_3y": percentiles[3],
            "percentile_5y": percentiles[5],
            "percentile_10y": percentile_10y,
            "zscore_5y_20d_change": zscore_5y_20d_change,
            "cooling_signal": cooling_signal,
            "overheating_signal": overheating_signal,
        },
    )


def unavailable(fetched_at: datetime, reason: str) -> IndicatorObservation:
    return unavailable_observation(
        indicator_id=IndicatorId.CREDIT_SPREAD_HY_OAS,
        indicator_name=INDICATOR_NAME,
        unit="pct",
        frequency=IndicatorFrequency.DAILY,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=series_url(SERIES_ID),
        reason=reason,
    )

from __future__ import annotations

import statistics
from datetime import date


def percentile_rank(historical_values: list[float], current_value: float) -> float | None:
    """current_value가 historical_values 안에서 몇 백분위인지 (0~100).

    historical_values가 비어있으면 계산 불가(None) - 임의의 기본값을 만들지 않는다.
    """
    if not historical_values:
        return None
    at_or_below = sum(1 for v in historical_values if v <= current_value)
    return round(100 * at_or_below / len(historical_values), 1)


def zscore(historical_values: list[float], current_value: float) -> float | None:
    """historical_values가 2개 미만이거나 표준편차가 0이면 계산 불가(None)."""
    if len(historical_values) < 2:
        return None
    mean = statistics.fmean(historical_values)
    stdev = statistics.stdev(historical_values)
    if stdev == 0:
        return None
    return round((current_value - mean) / stdev, 3)


def values_within_window(
    series: list[tuple[date, float]], as_of: date, window_days: int
) -> list[float]:
    """as_of 기준 최근 window_days(달력일) 이내 관측치 값 목록 (as_of 당일 포함, 백분위/
    z-score의 lookback 기간 계산용)."""
    cutoff = as_of.toordinal() - window_days
    return [v for d, v in series if cutoff <= d.toordinal() <= as_of.toordinal()]


def value_n_observations_back(series: list[tuple[date, float]], n: int) -> float | None:
    """series는 날짜 오름차순 정렬이라고 가정한다. 마지막 관측치 기준 n개 이전 관측치의 값
    (달력일이 아니라 관측치 개수 기준 - "20거래일 변화" 같은 계산에 쓴다)."""
    if len(series) <= n:
        return None
    return series[-1 - n][1]


def compute_changes(
    series: list[tuple[date, float]], lookbacks: list[int]
) -> dict[int, float | None]:
    """series(오름차순 정렬 가정)의 최신값 기준, 각 lookback(관측치 개수)만큼 이전 값과의
    차이. 여러 지표 collector가 반복하는 "N거래일 변화" 계산을 한 곳에 모은 것."""
    latest_value = series[-1][1] if series else None
    result: dict[int, float | None] = {}
    for n in lookbacks:
        older = value_n_observations_back(series, n)
        result[n] = None if (older is None or latest_value is None) else latest_value - older
    return result


def compute_percentiles(
    series: list[tuple[date, float]], as_of: date, windows_years: list[int]
) -> dict[int, float | None]:
    """series 최신값이 지난 N년 구간에서 몇 백분위인지, 요청한 N(년)마다."""
    current_value = series[-1][1] if series else None
    result: dict[int, float | None] = {}
    for years in windows_years:
        result[years] = (
            None
            if current_value is None
            else percentile_rank(values_within_window(series, as_of, 365 * years), current_value)
        )
    return result


def change_series(series: list[tuple[date, float]], n: int) -> list[tuple[date, float]]:
    """각 시점 t에서 t와 t-n(관측치 개수 기준) 사이 변화량 시계열 - "변화량 자체의 z-score"
    계산용 (예: 20거래일 변화가 5년래 얼마나 이례적인지)."""
    return [(series[i][0], series[i][1] - series[i - n][1]) for i in range(n, len(series))]

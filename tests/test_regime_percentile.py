from datetime import date

from investor_intel.regime.percentile import (
    change_series,
    compute_changes,
    compute_percentiles,
    percentile_rank,
    value_n_observations_back,
    values_within_window,
    zscore,
)


def test_percentile_rank_basic() -> None:
    assert percentile_rank([1, 2, 3, 4, 5], 3) == 60.0
    assert percentile_rank([1, 2, 3, 4, 5], 5) == 100.0
    assert percentile_rank([1, 2, 3, 4, 5], 0) == 0.0


def test_percentile_rank_empty_history_returns_none() -> None:
    assert percentile_rank([], 3) is None


def test_zscore_requires_at_least_two_points() -> None:
    assert zscore([1.0], 5.0) is None


def test_zscore_zero_stdev_returns_none() -> None:
    assert zscore([5.0, 5.0, 5.0], 5.0) is None


def test_zscore_basic() -> None:
    assert zscore([1.0, 2.0, 3.0, 4.0, 5.0], 5.0) is not None


def test_values_within_window_filters_by_calendar_days() -> None:
    series = [(date(2026, 1, 1), 1.0), (date(2026, 6, 1), 2.0), (date(2026, 7, 20), 3.0)]
    result = values_within_window(series, date(2026, 7, 30), 30)
    assert result == [3.0]


def test_value_n_observations_back() -> None:
    series = [(date(2026, 1, i), float(i)) for i in range(1, 11)]
    assert value_n_observations_back(series, 3) == 7.0
    assert value_n_observations_back(series, 20) is None


def test_compute_changes() -> None:
    series = [(date(2026, 1, i), float(i)) for i in range(1, 11)]
    result = compute_changes(series, [1, 5, 20])
    assert result[1] == 1.0
    assert result[5] == 5.0
    assert result[20] is None


def test_compute_percentiles_uses_window_and_as_of() -> None:
    series = [(date(2026, 1, 1), 1.0), (date(2026, 1, 2), 2.0), (date(2026, 1, 3), 3.0)]
    result = compute_percentiles(series, date(2026, 1, 3), [1])
    assert result[1] == 100.0


def test_change_series_pairs_each_point_with_n_back() -> None:
    series = [(date(2026, 1, i), float(i)) for i in range(1, 6)]
    result = change_series(series, 2)
    assert result == [
        (date(2026, 1, 3), 2.0),
        (date(2026, 1, 4), 2.0),
        (date(2026, 1, 5), 2.0),
    ]

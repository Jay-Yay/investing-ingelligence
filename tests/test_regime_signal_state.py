from datetime import UTC, date, datetime

from investor_intel.regime.models import (
    IndicatorFrequency,
    IndicatorId,
    IndicatorObservation,
    IndicatorStatus,
    SignalDirection,
    SignalStatus,
)
from investor_intel.regime.signal_state import build_signal

_NOW = datetime(2026, 1, 2, 9, tzinfo=UTC)


def _obs(
    details: dict | None = None,
    status: IndicatorStatus = IndicatorStatus.OK,
    obs_date: date = date(2026, 1, 2),
) -> IndicatorObservation:
    return IndicatorObservation(
        indicator_id=IndicatorId.CREDIT_SPREAD_HY_OAS,
        indicator_name="ICE BofA US High Yield OAS",
        value=3.5 if status == IndicatorStatus.OK else None,
        unit="pct",
        observation_date=obs_date,
        release_date=None,
        fetched_at=_NOW,
        source_name="FRED",
        source_url="https://example.com",
        frequency=IndicatorFrequency.DAILY,
        data_age_days=0,
        is_stale=False,
        is_revised=None,
        status=status,
        details=details or {},
    )


def test_unavailable_status_produces_unavailable_signal() -> None:
    obs = _obs(status=IndicatorStatus.UNAVAILABLE, details={"error_reason": "x"})
    signal = build_signal(obs, None)
    assert signal.status == SignalStatus.UNAVAILABLE


def test_no_fired_signal_and_no_history_is_normal() -> None:
    signal = build_signal(_obs(details={}), None)
    assert signal.status == SignalStatus.NORMAL
    assert signal.direction == SignalDirection.NEUTRAL


def test_first_time_signal_is_watch() -> None:
    signal = build_signal(_obs(details={"cooling_signal": True}), None)
    assert signal.status == SignalStatus.WATCH
    assert signal.direction == SignalDirection.COOLING


def test_signal_fired_two_days_in_a_row_is_confirmed() -> None:
    previous = _obs(details={"cooling_signal": True}, obs_date=date(2026, 1, 1))
    today = _obs(details={"cooling_signal": True}, obs_date=date(2026, 1, 2))
    signal = build_signal(today, previous)
    assert signal.status == SignalStatus.CONFIRMED


def test_signal_no_longer_firing_after_previously_firing_is_resolved() -> None:
    previous = _obs(details={"cooling_signal": True}, obs_date=date(2026, 1, 1))
    today = _obs(details={}, obs_date=date(2026, 1, 2))
    signal = build_signal(today, previous)
    assert signal.status == SignalStatus.RESOLVED


def test_highest_severity_signal_wins_when_multiple_fire() -> None:
    # credit_spread_hy_oas has both cooling_signal (severity 75) and overheating_signal (60)
    signal = build_signal(
        _obs(details={"cooling_signal": True, "overheating_signal": True}), None
    )
    assert signal.direction == SignalDirection.COOLING
    assert signal.severity == 75

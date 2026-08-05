from datetime import UTC, date, datetime
from pathlib import Path

from investor_intel.regime.history_store import (
    append_observations,
    latest_observation,
    read_history,
)
from investor_intel.regime.models import (
    IndicatorFrequency,
    IndicatorId,
    IndicatorObservation,
    IndicatorStatus,
)


def _obs(value: float, obs_date: date, fetched_at: datetime) -> IndicatorObservation:
    return IndicatorObservation(
        indicator_id=IndicatorId.CREDIT_SPREAD_HY_OAS,
        indicator_name="ICE BofA US High Yield OAS",
        value=value,
        unit="pct",
        observation_date=obs_date,
        release_date=None,
        fetched_at=fetched_at,
        source_name="FRED",
        source_url="https://fred.stlouisfed.org/series/BAMLH0A0HYM2",
        frequency=IndicatorFrequency.DAILY,
        data_age_days=0,
        is_stale=False,
        is_revised=None,
        status=IndicatorStatus.OK,
    )


def test_append_then_read_round_trips(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    obs = _obs(3.2, date(2026, 1, 1), datetime(2026, 1, 1, 9, tzinfo=UTC))
    written = append_observations(vault, IndicatorId.CREDIT_SPREAD_HY_OAS, [obs])
    assert written == 1

    history = read_history(vault, IndicatorId.CREDIT_SPREAD_HY_OAS)
    assert len(history) == 1
    assert history[0].value == 3.2


def test_same_day_rerun_with_identical_value_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    obs = _obs(3.2, date(2026, 1, 1), datetime(2026, 1, 1, 9, tzinfo=UTC))
    append_observations(vault, IndicatorId.CREDIT_SPREAD_HY_OAS, [obs])
    written_again = append_observations(vault, IndicatorId.CREDIT_SPREAD_HY_OAS, [obs])

    assert written_again == 0
    assert len(read_history(vault, IndicatorId.CREDIT_SPREAD_HY_OAS)) == 1


def test_same_day_rerun_with_changed_details_is_not_deduped(tmp_path: Path) -> None:
    """regime analyze-ai(Phase 2b)가 같은 날짜의 headline value/status는 그대로 두고
    details만 채워 넣는 시나리오 - value/status만 비교하면 이 갱신이 조용히 버려진다."""
    vault = tmp_path / "vault"
    first = _obs(3.2, date(2026, 1, 1), datetime(2026, 1, 1, 9, tzinfo=UTC))
    append_observations(vault, IndicatorId.CREDIT_SPREAD_HY_OAS, [first])

    enriched = first.model_copy(
        update={
            "fetched_at": datetime(2026, 1, 1, 15, tzinfo=UTC),
            "details": {"cloud_ai_revenue_growth_yoy": 35.0},
        }
    )
    written = append_observations(vault, IndicatorId.CREDIT_SPREAD_HY_OAS, [enriched])

    assert written == 1
    history = read_history(vault, IndicatorId.CREDIT_SPREAD_HY_OAS)
    assert len(history) == 2
    latest = latest_observation(history)
    assert latest is not None
    assert latest.details == {"cloud_ai_revenue_growth_yoy": 35.0}
    # value가 그대로이므로 is_revised는 False여야 한다 - details 변경은 개정이 아니다
    assert latest.is_revised is False


def test_revised_value_for_same_date_is_appended_and_flagged(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    first = _obs(3.2, date(2026, 1, 1), datetime(2026, 1, 1, 9, tzinfo=UTC))
    append_observations(vault, IndicatorId.CREDIT_SPREAD_HY_OAS, [first])

    revised = _obs(3.5, date(2026, 1, 1), datetime(2026, 1, 2, 9, tzinfo=UTC))
    written = append_observations(vault, IndicatorId.CREDIT_SPREAD_HY_OAS, [revised])

    assert written == 1
    history = read_history(vault, IndicatorId.CREDIT_SPREAD_HY_OAS)
    assert len(history) == 2
    assert history[-1].is_revised is True
    assert history[0].is_revised is None


def test_latest_observation_resolves_most_recent_date_and_fetch(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    day1 = _obs(3.2, date(2026, 1, 1), datetime(2026, 1, 1, 9, tzinfo=UTC))
    day2 = _obs(3.4, date(2026, 1, 2), datetime(2026, 1, 2, 9, tzinfo=UTC))
    append_observations(vault, IndicatorId.CREDIT_SPREAD_HY_OAS, [day1])
    append_observations(vault, IndicatorId.CREDIT_SPREAD_HY_OAS, [day2])

    latest = latest_observation(read_history(vault, IndicatorId.CREDIT_SPREAD_HY_OAS))
    assert latest is not None
    assert latest.value == 3.4
    assert latest.observation_date == date(2026, 1, 2)

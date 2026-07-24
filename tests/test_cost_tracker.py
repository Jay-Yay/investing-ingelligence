import pytest
from freezegun import freeze_time

from investor_intel.llm.cost_tracker import (
    CostTracker,
    UnknownModelPricingError,
    compute_cost_usd,
)
from investor_intel.storage.cost_ledger import init_cost_ledger
from investor_intel.storage.sqlite_index import connect


def _conn(tmp_path):
    conn = connect(tmp_path / "index.sqlite3")
    init_cost_ledger(conn)
    return conn


def test_compute_cost_usd_known_model() -> None:
    cost = compute_cost_usd("claude-sonnet-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(3.00 + 15.00)


def test_compute_cost_usd_unknown_model_raises() -> None:
    with pytest.raises(UnknownModelPricingError):
        compute_cost_usd("not-a-real-model", input_tokens=100, output_tokens=100)


@freeze_time("2026-07-24T15:00:00+09:00")
def test_record_usage_returns_and_persists_cost(tmp_path) -> None:
    tracker = CostTracker(_conn(tmp_path), daily_budget_usd=10.0, monthly_budget_usd=100.0)
    cost = tracker.record_usage("claude-sonnet-5", input_tokens=1_000_000, output_tokens=0)
    assert cost == pytest.approx(3.00)
    assert tracker.daily_total_usd() == pytest.approx(3.00)


@freeze_time("2026-07-24T23:30:00+09:00")
def test_daily_total_excludes_previous_kst_day(tmp_path) -> None:
    conn = _conn(tmp_path)
    tracker = CostTracker(conn, daily_budget_usd=10.0, monthly_budget_usd=100.0)
    tracker.record_usage("claude-sonnet-5", input_tokens=1_000_000, output_tokens=0)

    with freeze_time("2026-07-25T00:30:00+09:00"):
        next_day_tracker = CostTracker(conn, daily_budget_usd=10.0, monthly_budget_usd=100.0)
        assert next_day_tracker.daily_total_usd() == pytest.approx(0.0)


@freeze_time("2026-07-24T12:00:00+09:00")
def test_monthly_total_accumulates_across_days(tmp_path) -> None:
    conn = _conn(tmp_path)
    tracker = CostTracker(conn, daily_budget_usd=10.0, monthly_budget_usd=100.0)
    tracker.record_usage("claude-sonnet-5", input_tokens=1_000_000, output_tokens=0)

    with freeze_time("2026-07-25T12:00:00+09:00"):
        tracker2 = CostTracker(conn, daily_budget_usd=10.0, monthly_budget_usd=100.0)
        tracker2.record_usage("claude-sonnet-5", input_tokens=1_000_000, output_tokens=0)
        assert tracker2.monthly_total_usd() == pytest.approx(6.00)


@freeze_time("2026-07-24T12:00:00+09:00")
def test_is_within_budget_false_when_daily_budget_exceeded(tmp_path) -> None:
    conn = _conn(tmp_path)
    tracker = CostTracker(conn, daily_budget_usd=1.0, monthly_budget_usd=100.0)
    tracker.record_usage("claude-sonnet-5", input_tokens=1_000_000, output_tokens=0)
    assert tracker.is_within_budget() is False


@freeze_time("2026-07-24T12:00:00+09:00")
def test_is_within_budget_true_when_under_budget(tmp_path) -> None:
    conn = _conn(tmp_path)
    tracker = CostTracker(conn, daily_budget_usd=10.0, monthly_budget_usd=100.0)
    tracker.record_usage("claude-sonnet-5", input_tokens=1000, output_tokens=0)
    assert tracker.is_within_budget() is True

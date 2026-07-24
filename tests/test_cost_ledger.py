from datetime import UTC, datetime

from investor_intel.storage.cost_ledger import (
    init_cost_ledger,
    record_usage,
    sum_cost_between,
)
from investor_intel.storage.sqlite_index import connect


def _conn(tmp_path):
    conn = connect(tmp_path / "index.sqlite3")
    init_cost_ledger(conn)
    return conn


def test_record_usage_persists(tmp_path) -> None:
    conn = _conn(tmp_path)
    record_usage(
        conn,
        timestamp=datetime(2026, 7, 24, 3, 0, tzinfo=UTC),
        model="claude-sonnet-5",
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.0105,
    )
    total = sum_cost_between(
        conn,
        datetime(2026, 7, 24, 0, 0, tzinfo=UTC),
        datetime(2026, 7, 25, 0, 0, tzinfo=UTC),
    )
    assert total == 0.0105


def test_sum_cost_between_excludes_outside_range(tmp_path) -> None:
    conn = _conn(tmp_path)
    record_usage(
        conn,
        timestamp=datetime(2026, 7, 24, 3, 0, tzinfo=UTC),
        model="claude-sonnet-5",
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.01,
    )
    record_usage(
        conn,
        timestamp=datetime(2026, 7, 25, 3, 0, tzinfo=UTC),
        model="claude-sonnet-5",
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.02,
    )
    total = sum_cost_between(
        conn,
        datetime(2026, 7, 24, 0, 0, tzinfo=UTC),
        datetime(2026, 7, 25, 0, 0, tzinfo=UTC),
    )
    assert total == 0.01


def test_sum_cost_between_empty_range_is_zero(tmp_path) -> None:
    conn = _conn(tmp_path)
    total = sum_cost_between(
        conn,
        datetime(2026, 7, 24, 0, 0, tzinfo=UTC),
        datetime(2026, 7, 25, 0, 0, tzinfo=UTC),
    )
    assert total == 0.0

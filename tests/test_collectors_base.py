import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore, RateLimiter
from investor_intel.storage.sqlite_index import connect, init_db


def test_rate_limiter_enforces_minimum_interval() -> None:
    limiter = RateLimiter(max_per_second=5.0)  # min interval 0.2s
    start = time.monotonic()
    for _ in range(3):
        limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.4  # 2 waits of ~0.2s between 3 calls


def test_checkpoint_round_trip(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    store = CheckpointStore(conn)

    initial = store.get_state("telegram_allbareun")
    assert initial.last_seen_id is None
    assert initial.backfill_completed is False

    initial.last_seen_id = "42"
    initial.backfill_completed = True
    store.save_state(initial)

    reloaded = store.get_state("telegram_allbareun")
    assert reloaded.last_seen_id == "42"
    assert reloaded.backfill_completed is True


def test_record_failure_applies_exponential_backoff(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    store = CheckpointStore(conn)

    with freeze_time("2026-07-24T00:00:00+00:00"):
        state1 = store.record_failure("sec_13f_duquesne", base_backoff_seconds=60)
        assert state1.failure_count == 1
        assert state1.next_retry_at == datetime(2026, 7, 24, 0, 1, tzinfo=timezone.utc)

        state2 = store.record_failure("sec_13f_duquesne", base_backoff_seconds=60)
        assert state2.failure_count == 2
        assert state2.next_retry_at == datetime(2026, 7, 24, 0, 2, tzinfo=timezone.utc)


def test_record_success_resets_failure_count(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    store = CheckpointStore(conn)

    store.record_failure("dart_005930", base_backoff_seconds=60)
    store.record_failure("dart_005930", base_backoff_seconds=60)
    state = store.record_success("dart_005930", last_seen_id="20260724000123")

    assert state.failure_count == 0
    assert state.next_retry_at is None
    assert state.last_seen_id == "20260724000123"
    assert state.last_success_at is not None

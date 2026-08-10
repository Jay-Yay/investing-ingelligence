from pathlib import Path

from investor_intel.storage.checkpoint_file import load_checkpoints, save_checkpoints
from investor_intel.storage.sqlite_index import (
    connect,
    get_collector_state,
    init_db,
    save_collector_state,
)


def test_save_then_load_round_trips_checkpoint_across_a_fresh_db(tmp_path: Path) -> None:
    checkpoints_path = tmp_path / "checkpoints.json"

    writer_conn = connect(tmp_path / "writer.sqlite3")
    init_db(writer_conn)
    save_collector_state(
        writer_conn,
        source_id="bok_statements",
        last_success_at="2026-08-09T09:00:00+00:00",
        last_seen_id="KR-statement-2026-07-30",
        last_accession_number=None,
        failure_count=0,
        next_retry_at=None,
        backfill_completed=True,
    )
    save_checkpoints(writer_conn, checkpoints_path)
    assert checkpoints_path.exists()

    # a brand new sqlite file, exactly like the ephemeral index.sqlite3 that GH Actions
    # rebuilds from scratch every run - collector_state must start empty here.
    reader_conn = connect(tmp_path / "reader.sqlite3")
    init_db(reader_conn)
    assert get_collector_state(reader_conn, "bok_statements") is None

    load_checkpoints(reader_conn, checkpoints_path)

    row = get_collector_state(reader_conn, "bok_statements")
    assert row is not None
    assert row["last_seen_id"] == "KR-statement-2026-07-30"
    assert bool(row["backfill_completed"]) is True


def test_load_checkpoints_is_a_no_op_when_file_does_not_exist(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    load_checkpoints(conn, tmp_path / "missing-checkpoints.json")

    assert get_collector_state(conn, "anything") is None

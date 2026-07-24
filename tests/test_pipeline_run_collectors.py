from datetime import UTC, datetime

from investor_intel.collectors.base import CollectItem, CollectResult
from investor_intel.models.common import SourceType
from investor_intel.pipeline.collect import run_collectors
from investor_intel.storage.sqlite_index import connect, init_db


def _item(specific_id: str) -> CollectItem:
    return CollectItem(
        source_specific_id=specific_id,
        canonical_url=f"https://example.com/{specific_id}",
        title="제목",
        author="작성자",
        published_at=datetime(2026, 7, 24, tzinfo=UTC),
        updated_at=None,
        language="ko",
        body_text="본문",
        content_capture_mode="full",
    )


class _FakeCollector:
    def __init__(self, source_id: str, items: list[CollectItem], raises: bool = False):
        self.source_id = source_id
        self._items = items
        self._raises = raises
        self.backfill_calls: list[int] = []
        self.incremental_calls = 0

    def backfill(self, days: int) -> CollectResult:
        self.backfill_calls.append(days)
        if self._raises:
            raise RuntimeError("boom")
        return CollectResult(
            source_id=self.source_id,
            success=True,
            items=self._items,
            errors=[],
            new_count=len(self._items),
        )

    def collect_incremental(self) -> CollectResult:
        self.incremental_calls += 1
        if self._raises:
            raise RuntimeError("boom")
        return CollectResult(
            source_id=self.source_id,
            success=True,
            items=self._items,
            errors=[],
            new_count=len(self._items),
        )


def test_run_collectors_persists_each_source(tmp_path) -> None:
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    collector = _FakeCollector("naver_x", [_item("post-1")])
    results = run_collectors(
        [(collector, SourceType.NAVER, "engineerinvestor")], vault_path, conn
    )

    assert len(results) == 1
    assert results[0].source_id == "naver_x"
    assert results[0].persisted == 1
    assert results[0].errors == []
    assert collector.incremental_calls == 1


def test_run_collectors_uses_backfill_when_days_given(tmp_path) -> None:
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    collector = _FakeCollector("naver_x", [_item("post-1")])
    run_collectors(
        [(collector, SourceType.NAVER, "engineerinvestor")],
        vault_path,
        conn,
        backfill_days=30,
    )

    assert collector.backfill_calls == [30]
    assert collector.incremental_calls == 0


def test_one_failing_collector_does_not_stop_others(tmp_path) -> None:
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    failing = _FakeCollector("naver_bad", [], raises=True)
    healthy = _FakeCollector("naver_good", [_item("post-2")])

    results = run_collectors(
        [
            (failing, SourceType.NAVER, "bad_source"),
            (healthy, SourceType.NAVER, "good_source"),
        ],
        vault_path,
        conn,
    )

    assert results[0].source_id == "naver_bad"
    assert results[0].persisted == 0
    assert "boom" in results[0].errors[0]

    assert results[1].source_id == "naver_good"
    assert results[1].persisted == 1
    assert results[1].errors == []

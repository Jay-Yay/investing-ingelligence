from collections.abc import AsyncIterator
from datetime import UTC, datetime

from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.telegram_private import TelethonPrivateChannelCollector
from investor_intel.collectors.telethon_client import TelethonMessage
from investor_intel.models.config import SourceConfig
from investor_intel.storage.sqlite_index import connect, init_db


def _source() -> SourceConfig:
    return SourceConfig(
        id="telegram_private_allbareun",
        type="telegram_private",
        name="allbareun (비공개)",
        url="https://t.me/allbareun_private",
        author=None,
    )


class _FakeClient:
    def __init__(self, messages: list[TelethonMessage], error: Exception | None = None) -> None:
        self._messages = messages
        self._error = error
        self.calls: list[tuple[str, int]] = []

    async def iter_messages(self, entity: str, limit: int) -> AsyncIterator[TelethonMessage]:
        self.calls.append((entity, limit))
        if self._error is not None:
            raise self._error
        for message in self._messages:
            yield message


def _messages() -> list[TelethonMessage]:
    return [
        TelethonMessage(id=1, text="첫 메시지", date=datetime(2024, 5, 1, tzinfo=UTC)),
        TelethonMessage(id=2, text="두번째 메시지", date=datetime(2024, 5, 2, tzinfo=UTC)),
    ]


@freeze_time("2024-05-03")
def test_backfill_returns_only_in_window_messages(tmp_path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = _FakeClient(_messages())
    collector = TelethonPrivateChannelCollector(_source(), client, CheckpointStore(conn))

    result = collector.backfill(days=1)

    assert result.success
    assert result.new_count == 1
    item = result.items[0]
    assert item.source_specific_id == "2"
    assert item.canonical_url == "https://t.me/allbareun_private/2"
    assert item.content_capture_mode == "full"
    assert item.document_type == "telegram_message"
    assert client.calls == [("allbareun_private", 200)]


@freeze_time("2024-05-03")
def test_collect_incremental_is_idempotent(tmp_path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = _FakeClient(_messages())
    checkpoint_store = CheckpointStore(conn)

    first = TelethonPrivateChannelCollector(_source(), client, checkpoint_store)
    first_result = first.collect_incremental()
    assert first_result.new_count == 2

    second = TelethonPrivateChannelCollector(_source(), client, checkpoint_store)
    second_result = second.collect_incremental()

    assert second_result.new_count == 0
    assert second_result.items == []


@freeze_time("2024-05-03")
def test_backfill_handles_channel_private_error_gracefully(tmp_path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = _FakeClient([], error=RuntimeError("channel is private, not a member"))
    collector = TelethonPrivateChannelCollector(_source(), client, CheckpointStore(conn))

    result = collector.backfill(days=30)

    assert result.success is False
    assert result.items == []
    assert any("channel is private" in error for error in result.errors)


def test_source_id_matches_source_config(tmp_path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    collector = TelethonPrivateChannelCollector(
        _source(), _FakeClient([]), CheckpointStore(conn)
    )
    assert collector.source_id == "telegram_private_allbareun"

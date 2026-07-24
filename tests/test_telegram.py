from pathlib import Path

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.telegram import TelegramCollector
from investor_intel.models.config import SourceConfig
from investor_intel.storage.sqlite_index import connect, init_db

FIXTURES = Path(__file__).parent / "fixtures" / "telegram"


def _source() -> SourceConfig:
    return SourceConfig(
        id="telegram_allbareun",
        type="telegram",
        name="allbareun",
        url="https://t.me/s/allbareun",
        author=None,
    )


def _mock_preview() -> None:
    respx.get("https://t.me/s/allbareun").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "channel_preview.html").read_text(encoding="utf-8")
        )
    )


@respx.mock
@freeze_time("2024-05-03")
def test_backfill_returns_only_in_window_messages(tmp_path) -> None:
    _mock_preview()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    collector = TelegramCollector(_source(), client, CheckpointStore(conn))

    result = collector.backfill(days=1)
    client.close()

    assert result.success
    assert result.new_count == 1
    item = result.items[0]
    assert item.source_specific_id == "103"
    assert item.language == "ko"
    assert item.content_capture_mode == "full"
    assert item.document_type == "telegram_message"


@respx.mock
@freeze_time("2024-05-03")
def test_collect_incremental_is_idempotent(tmp_path) -> None:
    _mock_preview()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    checkpoint_store = CheckpointStore(conn)

    first_collector = TelegramCollector(_source(), client, checkpoint_store)
    first_result = first_collector.collect_incremental()
    # 3 messages in fixture, but the photo-only one has no text and is filtered by the parser
    assert first_result.new_count == 2

    second_collector = TelegramCollector(_source(), client, checkpoint_store)
    second_result = second_collector.collect_incremental()
    client.close()

    assert second_result.new_count == 0
    assert second_result.items == []


@respx.mock
@freeze_time("2024-05-03")
def test_source_id_matches_source_config(tmp_path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    collector = TelegramCollector(_source(), client, CheckpointStore(conn))
    client.close()
    assert collector.source_id == "telegram_allbareun"

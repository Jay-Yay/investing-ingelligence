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
    # respx matches routes in registration order and a bare `.get(url)` (no query constraint)
    # matches ANY query string for that path - the `?before=` route must be registered first,
    # or it's silently shadowed by the base route.
    respx.get(url__regex=r"https://t\.me/s/allbareun\?before=101").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "channel_preview_empty.html").read_text(encoding="utf-8")
        )
    )
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
def test_backfill_paginates_across_multiple_pages(tmp_path) -> None:
    # more specific (query-string) routes must be registered before the bare base-URL route -
    # respx matches in registration order and a bare `.get(url)` matches any query string
    respx.get(url__regex=r"https://t\.me/s/allbareun\?before=101").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "channel_preview_page2.html").read_text(encoding="utf-8")
        )
    )
    respx.get(url__regex=r"https://t\.me/s/allbareun\?before=99").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "channel_preview_empty.html").read_text(encoding="utf-8")
        )
    )
    respx.get("https://t.me/s/allbareun").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "channel_preview.html").read_text(encoding="utf-8")
        )
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    collector = TelegramCollector(_source(), client, CheckpointStore(conn))

    result = collector.backfill(days=30)
    client.close()

    assert result.success
    ids = {item.source_specific_id for item in result.items}
    # 2 text messages from page 1 (101, 103 - 102 is photo-only) + 1 from page 2 (99)
    assert ids == {"101", "103", "99"}


def _single_message_page(message_id: int) -> str:
    return f"""<!DOCTYPE html>
<html>
<body>
<div class="tgme_channel_history js-message_history">
  <div class="tgme_widget_message_wrap js-widget_message_wrap">
    <div class="tgme_widget_message js-widget_message" data-post="allbareun/{message_id}" \
data-view="x">
      <div class="tgme_widget_message_bubble">
        <div class="tgme_widget_message_text js-message_text" dir="auto">메시지 {message_id}</div>
        <div class="tgme_widget_message_footer compact js-message_footer">
          <div class="tgme_widget_message_info short js-message_info">
            <a class="tgme_widget_message_date" href="https://t.me/allbareun/{message_id}">
              <time class="time" datetime="2024-04-10T00:00:00+00:00">00:00</time>
            </a>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""


@respx.mock
@freeze_time("2024-05-03")
def test_fetch_stops_at_page_cap_without_ever_seeing_an_empty_page(tmp_path) -> None:
    def _decrementing_page(request: httpx.Request) -> httpx.Response:
        before = int(request.url.params["before"])
        return httpx.Response(200, text=_single_message_page(before - 1))

    # registered before the bare base-URL route - see the note in test_backfill_paginates_*
    respx.get(url__regex=r"https://t\.me/s/allbareun\?before=\d+").mock(
        side_effect=_decrementing_page
    )
    respx.get("https://t.me/s/allbareun").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "channel_preview.html").read_text(encoding="utf-8")
        )
    )

    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    collector = TelegramCollector(_source(), client, CheckpointStore(conn))

    result = collector.backfill(days=30)
    client.close()

    assert result.success
    # page 1 has 2 text messages (101, 103); every following page is brand-new (never empty,
    # never a duplicate) so the loop must be bounded by the page cap, not by natural exhaustion
    assert len(result.items) > 2
    assert len(result.items) < 300


@respx.mock
@freeze_time("2024-05-03")
def test_source_id_matches_source_config(tmp_path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    collector = TelegramCollector(_source(), client, CheckpointStore(conn))
    client.close()
    assert collector.source_id == "telegram_allbareun"

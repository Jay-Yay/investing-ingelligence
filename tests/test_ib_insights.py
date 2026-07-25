from datetime import date

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.ib_insights import IBInsightsCollector
from investor_intel.collectors.ib_insights_parser import IBArticle
from investor_intel.models.config import SourceConfig
from investor_intel.storage.sqlite_index import connect, init_db

_INDEX_URL = "https://example.com/insights"


def _source() -> SourceConfig:
    return SourceConfig(
        id="gs_insights_goldman_sachs",
        type="gs_insights",
        name="goldman-sachs",
        url=_INDEX_URL,
    )


def _collector(tmp_path, parse_index) -> tuple[IBInsightsCollector, CheckpointStore]:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    checkpoint_store = CheckpointStore(conn)
    client = SimpleHttpClient()
    collector = IBInsightsCollector(
        _source(), client, checkpoint_store, _INDEX_URL, parse_index
    )
    return collector, checkpoint_store


@respx.mock
def test_collect_incremental_first_run_processes_all_and_sets_checkpoint(tmp_path) -> None:
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    articles = [
        IBArticle("Newest", "https://example.com/a1", date(2026, 7, 20), "summary 1"),
        IBArticle("Older", "https://example.com/a2", date(2026, 7, 10), None),
    ]
    collector, checkpoint_store = _collector(tmp_path, lambda html: articles)

    result = collector.collect_incremental()

    assert result.success is True
    assert [item.canonical_url for item in result.items] == [
        "https://example.com/a1",
        "https://example.com/a2",
    ]
    state = checkpoint_store.get_state(collector.source_id)
    assert state.last_seen_id == "https://example.com/a1"


@respx.mock
def test_collect_incremental_second_run_only_returns_articles_above_checkpoint(tmp_path) -> None:
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    first_run_articles = [
        IBArticle("Newest", "https://example.com/a1", date(2026, 7, 20), "s1"),
        IBArticle("Older", "https://example.com/a2", date(2026, 7, 10), None),
    ]
    collector, checkpoint_store = _collector(tmp_path, lambda html: first_run_articles)
    collector.collect_incremental()

    second_run_articles = [
        IBArticle("Brand new", "https://example.com/a0", date(2026, 7, 25), "s0"),
        IBArticle("Newest", "https://example.com/a1", date(2026, 7, 20), "s1"),
        IBArticle("Older", "https://example.com/a2", date(2026, 7, 10), None),
    ]
    collector._parse_index = lambda html: second_run_articles

    result = collector.collect_incremental()

    assert [item.canonical_url for item in result.items] == ["https://example.com/a0"]
    state = checkpoint_store.get_state(collector.source_id)
    assert state.last_seen_id == "https://example.com/a0"


@respx.mock
def test_collect_incremental_returns_no_items_when_nothing_new(tmp_path) -> None:
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    articles = [IBArticle("Only", "https://example.com/a1", date(2026, 7, 20), "s1")]
    collector, checkpoint_store = _collector(tmp_path, lambda html: articles)
    collector.collect_incremental()

    result = collector.collect_incremental()

    assert result.items == []
    assert result.success is True


@respx.mock
@freeze_time("2026-07-24")
def test_backfill_filters_by_published_at_and_defaults_missing_date_to_today(tmp_path) -> None:
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    articles = [
        IBArticle("In window", "https://example.com/a1", date(2026, 7, 20), "s1"),
        IBArticle("Out of window", "https://example.com/a2", date(2025, 1, 1), None),
        IBArticle("No date - defaults to today", "https://example.com/a3", None, None),
    ]
    collector, _ = _collector(tmp_path, lambda html: articles)

    result = collector.backfill(days=7)

    urls = {item.canonical_url for item in result.items}
    assert urls == {"https://example.com/a1", "https://example.com/a3"}


@respx.mock
def test_build_item_content_capture_mode_reflects_summary_presence(tmp_path) -> None:
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    articles = [
        IBArticle("With summary", "https://example.com/a1", date(2026, 7, 20), "a real summary"),
        IBArticle("Without summary", "https://example.com/a2", date(2026, 7, 20), None),
    ]
    collector, _ = _collector(tmp_path, lambda html: articles)

    result = collector.collect_incremental()

    with_summary, without_summary = result.items
    assert with_summary.content_capture_mode == "excerpt"
    assert without_summary.content_capture_mode == "metadata_only"
    assert without_summary.content_capture_reason is not None

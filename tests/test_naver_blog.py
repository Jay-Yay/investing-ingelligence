from pathlib import Path

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.naver_blog import NaverBlogCollector
from investor_intel.models.config import SourceConfig
from investor_intel.storage.sqlite_index import connect, init_db

FIXTURES = Path(__file__).parent / "fixtures" / "naver"


def _source() -> SourceConfig:
    return SourceConfig(
        id="naver_engineerinvestor",
        type="naver",
        name="engineerinvestor",
        url="https://m.blog.naver.com/engineerinvestor",
        author="engineerinvestor",
    )


def _mock_rss() -> None:
    respx.get("https://rss.blog.naver.com/engineerinvestor.xml").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "rss_feed.xml").read_text(encoding="utf-8")
        )
    )
    _mock_post_view_detail()


def _mock_post_view_detail() -> None:
    post_view_html = (FIXTURES / "post_view.html").read_text(encoding="utf-8")
    for log_no in ("223456789", "223456790"):
        respx.get(
            f"https://blog.naver.com/PostView.naver?blogId=engineerinvestor&logNo={log_no}"
        ).mock(return_value=httpx.Response(200, text=post_view_html))


def _mock_rss_unavailable() -> None:
    respx.get("https://rss.blog.naver.com/engineerinvestor.xml").mock(
        return_value=httpx.Response(404)
    )


def _mock_html_fallback() -> None:
    respx.get(
        "https://blog.naver.com/PostTitleListAsync.naver"
        "?blogId=engineerinvestor&currentPage=1&categoryNo=&parentCategoryNo=&countPerPage=30"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "post_title_list_page1.json").read_text(encoding="utf-8")
        )
    )
    respx.get(
        "https://blog.naver.com/PostTitleListAsync.naver"
        "?blogId=engineerinvestor&currentPage=2&categoryNo=&parentCategoryNo=&countPerPage=30"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "post_title_list_empty.json").read_text(encoding="utf-8")
        )
    )
    post_view_html = (FIXTURES / "post_view.html").read_text(encoding="utf-8")
    respx.get(
        "https://blog.naver.com/PostView.naver?blogId=engineerinvestor&logNo=224355263150"
    ).mock(return_value=httpx.Response(200, text=post_view_html))
    respx.get(
        "https://blog.naver.com/PostView.naver?blogId=engineerinvestor&logNo=224356037349"
    ).mock(return_value=httpx.Response(200, text=post_view_html))


@respx.mock
@freeze_time("2024-05-03")
def test_backfill_returns_only_in_window_posts(tmp_path) -> None:
    _mock_rss()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    collector = NaverBlogCollector(_source(), client, CheckpointStore(conn))

    result = collector.backfill(days=1)
    client.close()

    assert result.success
    assert result.new_count == 1
    item = result.items[0]
    assert item.canonical_url == "https://blog.naver.com/engineerinvestor/223456790"
    assert item.language == "ko"
    assert item.content_capture_mode == "full"
    assert item.document_type == "blog_post"


@respx.mock
@freeze_time("2024-05-03")
def test_backfill_uses_full_body_from_detail_page_not_rss_summary(tmp_path) -> None:
    _mock_rss()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    collector = NaverBlogCollector(_source(), client, CheckpointStore(conn))

    result = collector.backfill(days=1)
    client.close()

    item = result.items[0]
    assert "매출과 CapEx가 동시에 증가했다" in item.body_text
    assert "엔비디아 이번 분기 실적이 시장 예상을 상회했다" not in item.body_text


@respx.mock
@freeze_time("2024-05-03")
def test_collect_incremental_is_idempotent(tmp_path) -> None:
    _mock_rss()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    checkpoint_store = CheckpointStore(conn)

    first_collector = NaverBlogCollector(_source(), client, checkpoint_store)
    first_result = first_collector.collect_incremental()
    assert first_result.new_count == 2

    second_collector = NaverBlogCollector(_source(), client, checkpoint_store)
    second_result = second_collector.collect_incremental()
    client.close()

    assert second_result.new_count == 0
    assert second_result.items == []


@respx.mock
@freeze_time("2026-07-24")
def test_backfill_falls_back_to_html_when_rss_unavailable(tmp_path) -> None:
    _mock_rss_unavailable()
    _mock_html_fallback()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    collector = NaverBlogCollector(_source(), client, CheckpointStore(conn))

    result = collector.backfill(days=1)
    client.close()

    assert result.success
    assert result.new_count == 2
    assert {item.canonical_url for item in result.items} == {
        "https://blog.naver.com/engineerinvestor/224355263150",
        "https://blog.naver.com/engineerinvestor/224356037349",
    }


@respx.mock
@freeze_time("2024-05-03")
def test_source_id_matches_source_config(tmp_path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    collector = NaverBlogCollector(_source(), client, CheckpointStore(conn))
    client.close()
    assert collector.source_id == "naver_engineerinvestor"

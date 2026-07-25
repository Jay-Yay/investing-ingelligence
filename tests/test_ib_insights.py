from datetime import date

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.ib_insights import IBInsightsCollector
from investor_intel.collectors.ib_insights_parser import IBArticle, find_pdf_href
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


def _collector(
    tmp_path, parse_index, *, pdf_link_finder=None, base_url: str = ""
) -> tuple[IBInsightsCollector, CheckpointStore]:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    checkpoint_store = CheckpointStore(conn)
    client = SimpleHttpClient()
    collector = IBInsightsCollector(
        _source(),
        client,
        checkpoint_store,
        _INDEX_URL,
        parse_index,
        base_url=base_url,
        pdf_link_finder=pdf_link_finder,
    )
    return collector, checkpoint_store


_VALID_PDF_WITH_TEXT = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>
/MediaBox[0 0 200 200]/Contents 5 0 R>>endobj
4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
5 0 obj<</Length 44>>
stream
BT /F1 12 Tf 10 100 Td (Hello PDF World) Tj ET
endstream
endobj
xref
0 6
trailer<</Size 6/Root 1 0 R>>
startxref
0
%%EOF"""


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


# --- PDF attachment fetching ---------------------------------------------------


_ARTICLE_URL = "https://example.com/report-article"
_PDF_URL = "https://example.com/files/report.pdf"


def _article() -> IBArticle:
    return IBArticle("Report", _ARTICLE_URL, date(2026, 7, 20), "teaser summary")


@respx.mock
def test_build_item_extracts_pdf_text_when_link_found(tmp_path) -> None:
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get(_ARTICLE_URL).mock(
        return_value=httpx.Response(200, text='<a href="/files/report.pdf">Download</a>')
    )
    respx.get(_PDF_URL).mock(
        return_value=httpx.Response(
            200, content=_VALID_PDF_WITH_TEXT, headers={"content-type": "application/pdf"}
        )
    )
    collector, _ = _collector(
        tmp_path,
        lambda html: [_article()],
        pdf_link_finder=find_pdf_href,
        base_url="https://example.com",
    )

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "full"
    assert item.content_capture_reason is None
    assert "Hello PDF World" in item.body_text


@respx.mock
def test_build_item_falls_back_to_teaser_when_no_pdf_link_found(tmp_path) -> None:
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get(_ARTICLE_URL).mock(
        return_value=httpx.Response(200, text="<p>just a regular article, no pdf</p>")
    )
    collector, _ = _collector(
        tmp_path,
        lambda html: [_article()],
        pdf_link_finder=find_pdf_href,
        base_url="https://example.com",
    )

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "excerpt"


@respx.mock
def test_build_item_falls_back_to_teaser_when_linked_file_is_not_actually_pdf(tmp_path) -> None:
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get(_ARTICLE_URL).mock(
        return_value=httpx.Response(200, text='<a href="/files/report.pdf">Download</a>')
    )
    respx.get(_PDF_URL).mock(
        return_value=httpx.Response(
            200, text="<html>not a pdf</html>", headers={"content-type": "text/html"}
        )
    )
    collector, _ = _collector(
        tmp_path,
        lambda html: [_article()],
        pdf_link_finder=find_pdf_href,
        base_url="https://example.com",
    )

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "excerpt"


@respx.mock
def test_build_item_extracts_pdf_served_as_octet_stream(tmp_path) -> None:
    # regression: Naver's static file server serves PDFs as application/octet-stream, not
    # application/pdf - detection must sniff the file's magic bytes, not trust the header.
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get(_ARTICLE_URL).mock(
        return_value=httpx.Response(200, text='<a href="/files/report.pdf">Download</a>')
    )
    respx.get(_PDF_URL).mock(
        return_value=httpx.Response(
            200,
            content=_VALID_PDF_WITH_TEXT,
            headers={"content-type": "application/octet-stream"},
        )
    )
    collector, _ = _collector(
        tmp_path,
        lambda html: [_article()],
        pdf_link_finder=find_pdf_href,
        base_url="https://example.com",
    )

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "full"
    assert "Hello PDF World" in item.body_text


@respx.mock
def test_build_item_falls_back_to_teaser_when_pdf_bytes_unreadable(tmp_path) -> None:
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get(_ARTICLE_URL).mock(
        return_value=httpx.Response(200, text='<a href="/files/report.pdf">Download</a>')
    )
    respx.get(_PDF_URL).mock(
        return_value=httpx.Response(
            200, content=b"not really a pdf", headers={"content-type": "application/pdf"}
        )
    )
    collector, _ = _collector(
        tmp_path,
        lambda html: [_article()],
        pdf_link_finder=find_pdf_href,
        base_url="https://example.com",
    )

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "excerpt"


@respx.mock
def test_build_item_falls_back_to_teaser_when_detail_page_fetch_fails(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get(_ARTICLE_URL).mock(return_value=httpx.Response(500))
    collector, _ = _collector(
        tmp_path,
        lambda html: [_article()],
        pdf_link_finder=find_pdf_href,
        base_url="https://example.com",
    )

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "excerpt"


@respx.mock
def test_build_item_skips_pdf_lookup_entirely_without_a_link_finder(tmp_path) -> None:
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    collector, _ = _collector(tmp_path, lambda html: [_article()])

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "excerpt"


@respx.mock
def test_build_item_content_capture_is_valid_for_every_mode(tmp_path) -> None:
    # regression test: ContentCapture (models/source_document.py) requires a non-empty reason
    # whenever mode != "full", and requires reason to be absent when mode == "full" - a mode
    # produced here without a matching reason would raise at document-build time, well after
    # collection succeeds, so assert against the real pydantic model rather than just the dict.
    from investor_intel.models.common import ContentCaptureMode
    from investor_intel.models.source_document import ContentCapture

    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get(_ARTICLE_URL).mock(
        return_value=httpx.Response(200, text='<a href="/files/report.pdf">Download</a>')
    )
    respx.get(_PDF_URL).mock(
        return_value=httpx.Response(
            200, content=_VALID_PDF_WITH_TEXT, headers={"content-type": "application/pdf"}
        )
    )
    no_pdf_url = "https://example.com/no-pdf-article"
    no_summary_url = "https://example.com/no-summary"
    respx.get(no_pdf_url).mock(
        return_value=httpx.Response(200, text="<p>no pdf link on this one</p>")
    )
    respx.get(no_summary_url).mock(
        return_value=httpx.Response(200, text="<p>no pdf link on this one either</p>")
    )
    articles = [
        _article(),
        IBArticle("Has summary, no PDF", no_pdf_url, date(2026, 7, 20), "a teaser"),
        IBArticle("No summary", no_summary_url, date(2026, 7, 20), None),
    ]
    collector, _ = _collector(
        tmp_path,
        lambda html: articles,
        pdf_link_finder=find_pdf_href,
        base_url="https://example.com",
    )

    result = collector.collect_incremental()

    modes = {item.content_capture_mode for item in result.items}
    assert modes == {"full", "excerpt", "metadata_only"}
    for item in result.items:
        ContentCapture(
            mode=ContentCaptureMode(item.content_capture_mode),
            reason=item.content_capture_reason,
        )


@respx.mock
def test_build_item_uses_pdf_url_directly_without_a_detail_page_fetch(tmp_path) -> None:
    # Naver research puts the PDF link on the listing row itself - no detail-page fetch, and
    # no pdf_link_finder, should be needed at all to reach it.
    respx.get(_INDEX_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get(_PDF_URL).mock(
        return_value=httpx.Response(
            200, content=_VALID_PDF_WITH_TEXT, headers={"content-type": "application/pdf"}
        )
    )
    article = IBArticle(
        "[SK텔레콤] 리포트 제목",
        _ARTICLE_URL,
        date(2026, 7, 24),
        None,
        pdf_url=_PDF_URL,
        author="신한투자증권",
    )
    collector, _ = _collector(tmp_path, lambda html: [article], base_url="https://example.com")

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "full"
    assert item.author == "신한투자증권"
    assert "Hello PDF World" in item.body_text

from datetime import date

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors import central_bank
from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.central_bank import CentralBankCollector, CentralBankSource
from investor_intel.collectors.central_bank_parser import CentralBankArticle
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.models.config import SourceConfig
from investor_intel.storage.sqlite_index import connect, init_db

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


def _source() -> SourceConfig:
    return SourceConfig(
        id="fed_statements", type="fed_statements", name="fed", url="https://example.com/index"
    )


def _collector(
    tmp_path, fetch_articles, **bank_kwargs
) -> tuple[CentralBankCollector, CheckpointStore]:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    checkpoint_store = CheckpointStore(conn)
    client = SimpleHttpClient()
    bank = CentralBankSource(
        bank_label="Fed",
        country="US",
        doc_kind="statement",
        fetch_articles=fetch_articles,
        **bank_kwargs,
    )
    collector = CentralBankCollector(_source(), client, checkpoint_store, bank)
    return collector, checkpoint_store


def _article(url="https://example.com/a1", meeting_date=date(2026, 6, 17), pdf_url=None):
    return CentralBankArticle(
        url=url, title="Test Statement", meeting_date=meeting_date, pdf_url=pdf_url
    )


def test_collect_incremental_first_run_processes_all_and_sets_checkpoint(tmp_path) -> None:
    articles = [
        _article("https://example.com/a1", date(2026, 6, 17)),
        _article("https://example.com/a2", date(2026, 4, 29)),
    ]
    collector, checkpoint_store = _collector(tmp_path, lambda client: articles)

    result = collector.collect_incremental()

    assert result.success is True
    assert [item.canonical_url for item in result.items] == [
        "https://example.com/a1",
        "https://example.com/a2",
    ]
    state = checkpoint_store.get_state(collector.source_id)
    assert state.last_seen_id == "https://example.com/a1"


def test_collect_incremental_second_run_only_returns_articles_above_checkpoint(tmp_path) -> None:
    first_run = [
        _article("https://example.com/a1", date(2026, 6, 17)),
        _article("https://example.com/a2", date(2026, 4, 29)),
    ]
    collector, checkpoint_store = _collector(tmp_path, lambda client: first_run)
    collector.collect_incremental()

    second_run = [
        _article("https://example.com/a0", date(2026, 7, 29)),
        _article("https://example.com/a1", date(2026, 6, 17)),
        _article("https://example.com/a2", date(2026, 4, 29)),
    ]
    collector._bank.fetch_articles = lambda client: second_run

    result = collector.collect_incremental()

    assert [item.canonical_url for item in result.items] == ["https://example.com/a0"]
    state = checkpoint_store.get_state(collector.source_id)
    assert state.last_seen_id == "https://example.com/a0"


def test_collect_incremental_returns_no_items_when_nothing_new(tmp_path) -> None:
    articles = [_article()]
    collector, _ = _collector(tmp_path, lambda client: articles)
    collector.collect_incremental()

    result = collector.collect_incremental()

    assert result.items == []
    assert result.success is True


def test_backfill_processes_everything_the_index_returns_and_marks_completed(tmp_path) -> None:
    articles = [_article("https://example.com/a1"), _article("https://example.com/a2")]
    collector, checkpoint_store = _collector(tmp_path, lambda client: articles)

    result = collector.backfill(days=365)

    assert len(result.items) == 2
    state = checkpoint_store.get_state(collector.source_id)
    assert state.backfill_completed is True


@respx.mock
def test_pdf_article_extracts_text_as_full_mode(tmp_path) -> None:
    respx.get("https://example.com/report.pdf").mock(
        return_value=httpx.Response(
            200, content=_VALID_PDF_WITH_TEXT, headers={"content-type": "application/pdf"}
        )
    )
    articles = [_article(pdf_url="https://example.com/report.pdf")]
    collector, _ = _collector(tmp_path, lambda client: articles)

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "full"
    assert "Hello PDF World" in item.body_text


@respx.mock
def test_pdf_article_falls_back_to_metadata_only_when_bytes_unreadable(tmp_path) -> None:
    respx.get("https://example.com/report.pdf").mock(
        return_value=httpx.Response(
            200, content=b"not really a pdf", headers={"content-type": "application/pdf"}
        )
    )
    articles = [_article(pdf_url="https://example.com/report.pdf")]
    collector, _ = _collector(tmp_path, lambda client: articles)

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "metadata_only"
    assert item.content_capture_reason is not None


@respx.mock
def test_html_article_uses_extract_html_when_provided(tmp_path) -> None:
    respx.get("https://example.com/a1").mock(
        return_value=httpx.Response(200, text="<div id='article'>real body text</div>")
    )
    articles = [_article("https://example.com/a1")]
    collector, _ = _collector(
        tmp_path,
        lambda client: articles,
        extract_html=lambda html: "real body text",
    )

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "full"
    assert "real body text" in item.body_text


def test_html_article_falls_back_to_metadata_only_without_extract_html(tmp_path) -> None:
    articles = [_article("https://example.com/a1")]
    collector, _ = _collector(tmp_path, lambda client: articles)

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "metadata_only"
    assert item.canonical_url == "https://example.com/a1"


def test_build_item_includes_claims_splice_headers(tmp_path) -> None:
    # regression: pipeline/claims_splice.py only injects extracted claims back into the body
    # when these exact headers are already present (see ib_insights_document.py convention).
    articles = [_article()]
    collector, _ = _collector(tmp_path, lambda client: articles)

    result = collector.collect_incremental()

    (item,) = result.items
    for header in ("## 핵심 주장", "## 근거", "## 반대 근거", "## 언급 자산"):
        assert header in item.body_text


def test_build_item_tags_country_and_document_type(tmp_path) -> None:
    articles = [_article(meeting_date=date(2026, 6, 17))]
    collector, _ = _collector(tmp_path, lambda client: articles)

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.themes == ["macro", "central_bank", "US"]
    assert item.document_type == "central_bank_statement"
    assert item.reporting_period == "2026-06-17"
    assert item.companies == []


@freeze_time("2026-07-01T00:00:00+00:00")
def test_published_at_is_collection_time_not_meeting_date(tmp_path) -> None:
    # regression: if published_at were the meeting date, minutes published weeks later would
    # fall outside analyze's "recent N days" follow-up window and be silently skipped.
    articles = [_article(meeting_date=date(2026, 1, 1))]
    collector, _ = _collector(tmp_path, lambda client: articles)

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.published_at.isoformat().startswith("2026-07-01")


@respx.mock
@freeze_time("2026-08-01T00:00:00+00:00")
def test_fetch_ecb_statements_sorts_desc_even_when_index_lists_old_year_first() -> None:
    # regression: ECB's own data-snippets list order isn't guaranteed newest-first - if it lists
    # the older year before the current year, naively concatenating per-year results (each
    # individually sorted desc) yields a globally out-of-order list, which would corrupt
    # collect_incremental's checkpoint (see dedupe_sort_desc docstring in central_bank_parser.py).
    index_url = "https://www.ecb.europa.eu/press/press_conference/monetary-policy-statement/html/index.en.html"
    respx.get(index_url).mock(
        return_value=httpx.Response(
            200,
            text=(
                "<dl id=\"lazyload-container\" data-snippets='../2025/html/index_include.en.html,"
                "../2026/html/index_include.en.html'></dl>"
            ),
        )
    )
    old_year_url = (
        "https://www.ecb.europa.eu/press/press_conference/monetary-policy-statement/"
        "2025/html/index_include.en.html"
    )
    current_year_url = (
        "https://www.ecb.europa.eu/press/press_conference/monetary-policy-statement/"
        "2026/html/index_include.en.html"
    )
    respx.get(old_year_url).mock(
        return_value=httpx.Response(
            200,
            text=(
                '<a href="/press/press_conference/monetary-policy-statement/2025/html/'
                'ecb.is251218~aaaaaaaaaa.en.html">Statement</a>'
            ),
        )
    )
    respx.get(current_year_url).mock(
        return_value=httpx.Response(
            200,
            text=(
                '<a href="/press/press_conference/monetary-policy-statement/2026/html/'
                'ecb.is260617~bbbbbbbbbb.en.html">Statement</a>'
            ),
        )
    )

    articles = central_bank._fetch_ecb_statements(SimpleHttpClient())

    assert [a.meeting_date for a in articles] == [date(2026, 6, 17), date(2025, 12, 18)]


def test_source_specific_id_is_stable_across_doc_kinds(tmp_path) -> None:
    articles = [_article(meeting_date=date(2026, 6, 17))]
    conn_path = tmp_path / "index.sqlite3"
    conn = connect(conn_path)
    init_db(conn)
    checkpoint_store = CheckpointStore(conn)
    client = SimpleHttpClient()
    minutes_bank = CentralBankSource(
        bank_label="Fed", country="US", doc_kind="minutes", fetch_articles=lambda client: articles
    )
    collector = CentralBankCollector(_source(), client, checkpoint_store, minutes_bank)

    (item,) = collector.collect_incremental().items

    assert item.source_specific_id == "US-minutes-2026-06-17"

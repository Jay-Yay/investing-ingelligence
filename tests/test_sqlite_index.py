from datetime import UTC, datetime
from pathlib import Path

from investor_intel.collectors.base import CollectItem, CollectResult
from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import ContentCapture, SourceDocument
from investor_intel.pipeline.collect import persist_collect_result
from investor_intel.storage.content_hash import compute_content_hash, compute_stable_id
from investor_intel.storage.obsidian_repo import write_document
from investor_intel.storage.sqlite_index import (
    connect,
    export_collector_state,
    find_dart_company_by_stock_code,
    find_dart_corp_code,
    find_duplicate,
    get_collector_state,
    get_document_by_id,
    has_transcript_for_period,
    import_collector_state,
    init_db,
    is_dart_corp_code_cache_populated,
    reindex,
    replace_dart_corp_codes,
    save_collector_state,
    upsert_document,
)


def _make_doc(
    body: str, url: str = "https://t.me/x/1", source_specific_id: str = "1"
) -> SourceDocument:
    now = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
    return SourceDocument(
        id=compute_stable_id("telegram", "allbareun", source_specific_id, url),
        source_type=SourceType.TELEGRAM,
        source_name="allbareun",
        source_url=url,
        source_specific_id=source_specific_id,
        published_at=now,
        collected_at=now,
        language="ko",
        content_hash=compute_content_hash(body),
        content_capture=ContentCapture(mode=ContentCaptureMode.FULL),
        document_type="opinion",
    )


def test_upsert_and_get_document(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    doc = _make_doc("본문")
    upsert_document(conn, doc, "10_Sources/Telegram/allbareun/2026/x.md", source_specific_id="1")
    row = get_document_by_id(conn, doc.id)
    assert row is not None
    assert row["source_name"] == "allbareun"


def test_upsert_is_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    doc = _make_doc("본문")
    upsert_document(conn, doc, "path.md", source_specific_id="1")
    upsert_document(conn, doc, "path.md", source_specific_id="1")
    count = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
    assert count == 1


def test_find_duplicate_by_source_specific_id(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    doc = _make_doc("본문")
    upsert_document(conn, doc, "path.md", source_specific_id="1")
    found = find_duplicate(
        conn, "telegram", "allbareun", "1", "https://t.me/x/1-different",
        compute_content_hash("다른 본문"), None, None, doc.published_at.isoformat(),
    )
    assert found == doc.id


def test_find_duplicate_by_canonical_url(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    doc = _make_doc("본문")
    upsert_document(conn, doc, "path.md", source_specific_id="1")
    found = find_duplicate(
        conn, "telegram", "allbareun", "different-id", doc.source_url,
        compute_content_hash("다른 본문"), None, None, doc.published_at.isoformat(),
    )
    assert found == doc.id


def test_find_duplicate_by_content_hash(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    doc = _make_doc("동일한 본문")
    upsert_document(conn, doc, "path.md", source_specific_id="1")
    found = find_duplicate(
        conn, "telegram", "allbareun", "different-id", "https://t.me/x/other",
        compute_content_hash("동일한 본문"), None, None, doc.published_at.isoformat(),
    )
    assert found == doc.id


def test_find_duplicate_by_title_author_published_at(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    doc = _make_doc("본문")
    doc.title = "동일 제목"
    doc.author = "홍길동"
    upsert_document(conn, doc, "path.md", source_specific_id="1")
    found = find_duplicate(
        conn, "telegram", "allbareun", "different-id", "https://t.me/x/other",
        compute_content_hash("다른 본문"), doc.title, doc.author, doc.published_at.isoformat(),
    )
    assert found == doc.id


def test_find_duplicate_by_title_published_at_with_null_author(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    doc = _make_doc("본문")
    doc.title = "익명 게시물"
    doc.author = None
    upsert_document(conn, doc, "path.md", source_specific_id="1")
    found = find_duplicate(
        conn, "telegram", "allbareun", "different-id", "https://t.me/x/other",
        compute_content_hash("다른 본문"), doc.title, None, doc.published_at.isoformat(),
    )
    assert found == doc.id


def test_find_duplicate_returns_none_when_no_match(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    found = find_duplicate(
        conn, "telegram", "allbareun", "1", "https://t.me/x/1",
        compute_content_hash("본문"), None, None, "2026-07-24T09:00:00+00:00",
    )
    assert found is None


def test_reindex_rebuilds_from_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_document(
        vault,
        _make_doc("첫번째", url="https://t.me/x/1", source_specific_id="1"),
        "## 원문\n\n첫번째\n",
    )
    write_document(
        vault,
        _make_doc("두번째", url="https://t.me/x/2", source_specific_id="2"),
        "## 원문\n\n두번째\n",
    )

    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    count = reindex(conn, vault)
    assert count == 2
    total = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
    assert total == 2


def test_reindex_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_document(vault, _make_doc("첫번째"), "## 원문\n\n첫번째\n")
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    reindex(conn, vault)
    reindex(conn, vault)
    total = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
    assert total == 1


def test_reindex_preserves_source_specific_id_for_dedup(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    doc_a = _make_doc("첫번째", url="https://t.me/x/1", source_specific_id="msg-1")
    doc_b = _make_doc("두번째", url="https://t.me/x/2", source_specific_id="msg-2")
    write_document(vault, doc_a, "## 원문\n\n첫번째\n")
    write_document(vault, doc_b, "## 원문\n\n두번째\n")

    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    count = reindex(conn, vault)
    assert count == 2

    # Same source_specific_id as doc_a, but a completely different canonical_url,
    # content_hash, title, author, and published_at - only source_specific_id
    # should match. If reindex lost source_specific_id (set it to NULL), this
    # lookup would fall through to the other dedup steps and find nothing.
    found = find_duplicate(
        conn,
        "telegram",
        "allbareun",
        "msg-1",
        "https://t.me/x/1-completely-different-url",
        compute_content_hash("전혀 다른 내용"),
        "다른 제목",
        "다른 작성자",
        "2099-01-01T00:00:00+00:00",
    )
    assert found == doc_a.id


def test_persist_collect_result_stores_same_file_path_representation_as_reindex(
    tmp_path: Path,
) -> None:
    """persist_collect_result() and reindex() must record documents.file_path in the same
    form (vault-relative), otherwise whichever path last wrote the row determines whether
    downstream readers (analyze.py etc.) can open the file at all - see P0 in
    docs/plans/analyze-cost-reduction.md."""
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    item = CollectItem(
        source_specific_id="acc-1",
        canonical_url="https://example.com/doc-1",
        title="Example title",
        author="Example Author",
        published_at=datetime(2026, 7, 24, tzinfo=UTC),
        updated_at=None,
        language="ko",
        body_text="본문 내용입니다.",
        content_capture_mode="full",
    )
    result = CollectResult(
        source_id="naver_x", success=True, items=[item], errors=[], new_count=1
    )
    persist_collect_result(
        result,
        source_type=SourceType.NAVER,
        source_name="engineerinvestor",
        vault_path=vault_path,
        conn=conn,
    )

    row = conn.execute("SELECT id, file_path FROM documents").fetchone()
    persisted_file_path = row["file_path"]
    assert not Path(persisted_file_path).is_absolute()
    assert (vault_path / persisted_file_path).exists()

    reindex(conn, vault_path)

    reindexed_row = get_document_by_id(conn, row["id"])
    assert reindexed_row["file_path"] == persisted_file_path


def test_collector_state_round_trip(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    assert get_collector_state(conn, "telegram_allbareun") is None
    save_collector_state(
        conn,
        source_id="telegram_allbareun",
        last_success_at="2026-07-24T09:00:00+00:00",
        last_seen_id="123",
        last_accession_number=None,
        failure_count=0,
        next_retry_at=None,
        backfill_completed=True,
    )
    row = get_collector_state(conn, "telegram_allbareun")
    assert row is not None
    assert row["last_seen_id"] == "123"
    assert bool(row["backfill_completed"]) is True


def test_collector_state_export_import_round_trip(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    save_collector_state(
        conn,
        source_id="fed_statements",
        last_success_at="2026-08-09T09:00:00+00:00",
        last_seen_id="https://www.federalreserve.gov/2026-07-30",
        last_accession_number=None,
        failure_count=0,
        next_retry_at=None,
        backfill_completed=True,
    )

    exported = export_collector_state(conn)
    assert exported["fed_statements"]["last_seen_id"] == (
        "https://www.federalreserve.gov/2026-07-30"
    )

    fresh_conn = connect(tmp_path / "reindexed.sqlite3")
    init_db(fresh_conn)
    assert get_collector_state(fresh_conn, "fed_statements") is None

    import_collector_state(fresh_conn, exported)

    row = get_collector_state(fresh_conn, "fed_statements")
    assert row is not None
    assert row["last_seen_id"] == "https://www.federalreserve.gov/2026-07-30"
    assert bool(row["backfill_completed"]) is True


def _entries() -> list[tuple[str, str, str | None, str]]:
    return [
        ("00126380", "삼성전자", "005930", "20260101"),
        ("00999999", "비상장회사", None, "20260102"),
    ]


def test_dart_corp_code_cache_starts_empty(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    assert is_dart_corp_code_cache_populated(conn) is False
    assert find_dart_corp_code(conn, stock_code="005930", name=None) is None


def test_replace_dart_corp_codes_enables_lookup_by_stock_code_or_name(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    replace_dart_corp_codes(conn, _entries())

    assert is_dart_corp_code_cache_populated(conn) is True
    assert find_dart_corp_code(conn, stock_code="005930", name=None) == "00126380"
    assert find_dart_corp_code(conn, stock_code=None, name="비상장회사") == "00999999"
    assert find_dart_corp_code(conn, stock_code="000000", name=None) is None


def test_replace_dart_corp_codes_clears_previous_entries(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    replace_dart_corp_codes(conn, _entries())
    replace_dart_corp_codes(conn, [("00111111", "새회사", "123456", "20260103")])

    assert find_dart_corp_code(conn, stock_code="005930", name=None) is None
    assert find_dart_corp_code(conn, stock_code="123456", name=None) == "00111111"


def test_find_dart_company_by_stock_code_returns_code_and_name(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    replace_dart_corp_codes(conn, _entries())

    assert find_dart_company_by_stock_code(conn, "005930") == ("00126380", "삼성전자")
    assert find_dart_company_by_stock_code(conn, "000000") is None


def _make_sec_filing_doc(
    ticker: str,
    title: str,
    filing_type: str = "8-K",
    reporting_period: str | None = "2026-06-30",
    source_specific_id: str = "0001-24-000001",
) -> SourceDocument:
    now = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
    return SourceDocument(
        id=compute_stable_id("sec_filing", ticker, source_specific_id, f"https://sec.gov/{ticker}"),
        source_type=SourceType.SEC_FILING,
        source_name=ticker,
        source_url=f"https://sec.gov/{ticker}",
        source_specific_id=source_specific_id,
        title=title,
        published_at=now,
        collected_at=now,
        language="en",
        content_hash=compute_content_hash(title),
        content_capture=ContentCapture(mode=ContentCaptureMode.FULL),
        document_type="sec_filing",
        filing_type=filing_type,
        reporting_period=reporting_period,
        accession_number=source_specific_id,
    )


def test_upsert_document_marks_is_transcript_for_8k_with_transcript_title(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    doc = _make_sec_filing_doc("BE", "[컨퍼런스콜] Bloom Energy 8-K (2026-06-30)")
    upsert_document(conn, doc, "path.md")
    row = get_document_by_id(conn, doc.id)
    assert row["is_transcript"] == 1
    assert row["reporting_period"] == "2026-06-30"


def test_upsert_document_does_not_mark_is_transcript_for_plain_8k(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    doc = _make_sec_filing_doc("BE", "Bloom Energy 8-K (2026-06-30)")
    upsert_document(conn, doc, "path.md")
    row = get_document_by_id(conn, doc.id)
    assert row["is_transcript"] == 0


def test_upsert_document_marks_is_transcript_for_earnings_call_transcript_type(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    doc = _make_sec_filing_doc("BE", "[컨퍼런스콜-웹서치] Bloom Energy 2026-06-30 실적발표")
    doc = doc.model_copy(update={"document_type": "earnings_call_transcript", "filing_type": None})
    upsert_document(conn, doc, "path.md")
    row = get_document_by_id(conn, doc.id)
    assert row["is_transcript"] == 1


def test_has_transcript_for_period_true_when_indexed(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    doc = _make_sec_filing_doc("BE", "[컨퍼런스콜] Bloom Energy 8-K (2026-06-30)")
    upsert_document(conn, doc, "path.md")
    assert has_transcript_for_period(conn, "BE", "2026-06-30") is True


def test_has_transcript_for_period_false_for_different_period_or_ticker(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    doc = _make_sec_filing_doc("BE", "[컨퍼런스콜] Bloom Energy 8-K (2026-06-30)")
    upsert_document(conn, doc, "path.md")
    assert has_transcript_for_period(conn, "BE", "2026-03-31") is False
    assert has_transcript_for_period(conn, "RDDT", "2026-06-30") is False


def test_has_transcript_for_period_false_when_only_metadata_only_8k_present(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    doc = _make_sec_filing_doc("BE", "Bloom Energy 8-K (2026-06-30)")
    upsert_document(conn, doc, "path.md")
    assert has_transcript_for_period(conn, "BE", "2026-06-30") is False


def test_init_db_migrates_legacy_documents_table_missing_new_columns(tmp_path: Path) -> None:
    # regression: a sqlite file created before reporting_period/is_transcript existed shouldn't
    # break on the next init_db() - `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table,
    # so the new columns must be added via ALTER TABLE instead.
    conn = connect(tmp_path / "index.sqlite3")
    conn.execute(
        """
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_specific_id TEXT,
            canonical_url TEXT NOT NULL,
            title TEXT,
            author TEXT,
            published_at TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            document_type TEXT NOT NULL,
            filing_type TEXT,
            accession_number TEXT,
            llm_processed INTEGER NOT NULL DEFAULT 0,
            file_path TEXT NOT NULL
        )
        """
    )
    conn.commit()

    init_db(conn)

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(documents)")}
    assert "reporting_period" in columns
    assert "is_transcript" in columns

    doc = _make_doc("본문")
    upsert_document(conn, doc, "path.md", source_specific_id="1")
    assert get_document_by_id(conn, doc.id) is not None

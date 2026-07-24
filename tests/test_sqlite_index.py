from datetime import UTC, datetime
from pathlib import Path

from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import ContentCapture, SourceDocument
from investor_intel.storage.content_hash import compute_content_hash, compute_stable_id
from investor_intel.storage.obsidian_repo import write_document
from investor_intel.storage.sqlite_index import (
    connect,
    find_duplicate,
    get_collector_state,
    get_document_by_id,
    init_db,
    reindex,
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

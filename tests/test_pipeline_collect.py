from datetime import UTC, datetime

from investor_intel.collectors.base import CollectItem, CollectResult
from investor_intel.models.common import SourceType
from investor_intel.pipeline.collect import collect_item_to_source_document, persist_collect_result
from investor_intel.storage.sqlite_index import connect, get_document_by_id, init_db


def _item(**overrides) -> CollectItem:
    defaults = dict(
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
    defaults.update(overrides)
    return CollectItem(**defaults)


def test_conversion_produces_valid_full_mode_document() -> None:
    doc, body = collect_item_to_source_document(
        _item(), source_type=SourceType.NAVER, source_name="engineerinvestor"
    )
    assert body == "본문 내용입니다."
    assert doc.content_capture.mode.value == "full"
    assert doc.content_capture.reason is None
    assert doc.source_type == SourceType.NAVER


def test_conversion_produces_valid_metadata_only_document() -> None:
    doc, _ = collect_item_to_source_document(
        _item(
            content_capture_mode="metadata_only",
            content_capture_reason="raw filing not parsed in this phase",
        ),
        source_type=SourceType.SEC_FILING,
        source_name="BE",
    )
    assert doc.content_capture.mode.value == "metadata_only"
    assert doc.content_capture.reason == "raw filing not parsed in this phase"


def test_persist_writes_document_and_index_row(tmp_path) -> None:
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    result = CollectResult(
        source_id="naver_x", success=True, items=[_item()], errors=[], new_count=1
    )
    persisted = persist_collect_result(
        result, source_type=SourceType.NAVER, source_name="engineerinvestor",
        vault_path=vault_path, conn=conn,
    )

    assert persisted.count == 1
    doc, _ = collect_item_to_source_document(
        _item(), source_type=SourceType.NAVER, source_name="engineerinvestor"
    )
    row = get_document_by_id(conn, doc.id)
    assert row is not None
    assert (vault_path).exists()


def test_persist_is_idempotent_on_rerun(tmp_path) -> None:
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    result = CollectResult(
        source_id="naver_x", success=True, items=[_item()], errors=[], new_count=1
    )
    persist_collect_result(
        result, source_type=SourceType.NAVER, source_name="engineerinvestor",
        vault_path=vault_path, conn=conn,
    )
    files_after_first = list(vault_path.rglob("*.md"))

    second = persist_collect_result(
        result, source_type=SourceType.NAVER, source_name="engineerinvestor",
        vault_path=vault_path, conn=conn,
    )
    files_after_second = list(vault_path.rglob("*.md"))

    # 내용이 그대로면 파일도 DB도 건드리지 않고 skipped로만 집계한다.
    assert second.count == 0
    assert second.skipped == 1
    assert files_after_first == files_after_second


def test_persist_reuses_existing_id_when_duplicate_detected_via_content_hash(tmp_path) -> None:
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    first_item = _item(source_specific_id="acc-1", canonical_url="https://example.com/doc-1")
    persist_collect_result(
        CollectResult(
            source_id="naver_x", success=True, items=[first_item], errors=[], new_count=1
        ),
        source_type=SourceType.NAVER, source_name="engineerinvestor",
        vault_path=vault_path, conn=conn,
    )

    # same content, but a different canonical_url and no source_specific_id this time —
    # find_duplicate must still catch it via content_hash and reuse the same id
    republished_item = _item(
        source_specific_id=None, canonical_url="https://example.com/doc-1-republished"
    )
    second = persist_collect_result(
        CollectResult(
            source_id="naver_x", success=True, items=[republished_item], errors=[], new_count=1
        ),
        source_type=SourceType.NAVER, source_name="engineerinvestor",
        vault_path=vault_path, conn=conn,
    )

    # 같은 내용이 다른 URL로 재게시된 것이므로 기존 id를 재사용하고 새 파일을 만들지 않는다.
    assert second.count == 0
    assert second.skipped == 1
    files = list(vault_path.rglob("*.md"))
    assert len(files) == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == 1


def _persist(vault_path, conn, item):
    return persist_collect_result(
        CollectResult(source_id="cb_boj", success=True, items=[item], errors=[], new_count=1),
        source_type=SourceType.CENTRAL_BANK,
        source_name="boj",
        vault_path=vault_path,
        conn=conn,
    )


def _vault_files(vault_path):
    return sorted(p for p in vault_path.rglob("*.md"))


def test_recollecting_same_document_with_new_published_at_does_not_duplicate_file(
    tmp_path,
) -> None:
    """`path_for_document`가 파일명을 published_at으로 만드는데, central_bank는 회의록이
    늦게 공개돼도 recency 창에 걸리도록 published_at=now를 쓴다. 그래서 재수집할 때마다
    경로가 달라져 같은 문서의 사본이 계속 쌓였다(실측: 271개 id / 초과 파일 678개 / 20.4MB).
    """
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    _persist(vault_path, conn, _item(published_at=datetime(2026, 8, 1, tzinfo=UTC)))
    second = _persist(vault_path, conn, _item(published_at=datetime(2026, 8, 5, tzinfo=UTC)))

    assert len(_vault_files(vault_path)) == 1
    # 내용이 같으므로 파일도 DB도 건드리지 않고 건너뛴다.
    assert second.count == 0
    assert second.skipped == 1


def test_recollected_document_with_changed_content_is_updated_in_place(tmp_path) -> None:
    """내용이 실제로 바뀐 재수집은 기존 파일을 제자리에서 갱신하고 재분석 대상으로 되돌린다."""
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    _persist(vault_path, conn, _item(published_at=datetime(2026, 8, 1, tzinfo=UTC)))
    row = conn.execute("SELECT id, file_path FROM documents").fetchone()
    doc_id, original_path = row["id"], row["file_path"]
    conn.execute("UPDATE documents SET llm_processed = 1 WHERE id = ?", (doc_id,))
    conn.commit()

    result = _persist(
        vault_path,
        conn,
        _item(published_at=datetime(2026, 8, 5, tzinfo=UTC), body_text="개정된 본문입니다."),
    )

    assert result.count == 1
    assert result.skipped == 0
    assert len(_vault_files(vault_path)) == 1
    updated = get_document_by_id(conn, doc_id)
    # 경로는 그대로 유지하고, 내용이 달라졌으므로 재분석 대상으로 되돌린다.
    assert updated["file_path"] == original_path
    assert updated["llm_processed"] == 0
    assert "개정된 본문입니다." in (vault_path / original_path).read_text(encoding="utf-8")

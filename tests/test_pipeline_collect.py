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

    assert second.count == 1
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

    assert second.count == 1
    files = list(vault_path.rglob("*.md"))
    assert len(files) == 1

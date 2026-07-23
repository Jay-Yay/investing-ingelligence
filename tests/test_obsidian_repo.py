from datetime import UTC, datetime
from pathlib import Path

from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import ContentCapture, SourceDocument
from investor_intel.storage.content_hash import compute_content_hash, compute_stable_id
from investor_intel.storage.obsidian_repo import (
    list_documents,
    path_for_document,
    read_document,
    sanitize_path_component,
    write_document,
)


def _make_doc(
    body: str,
    source_name: str = "allbareun",
    doc_id: str | None = None,
    source_specific_id: str | None = None,
) -> SourceDocument:
    now = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
    return SourceDocument(
        id=doc_id or compute_stable_id("telegram", source_name, "1", "https://t.me/x/1"),
        source_type=SourceType.TELEGRAM,
        source_name=source_name,
        source_url="https://t.me/x/1",
        source_specific_id=source_specific_id,
        published_at=now,
        collected_at=now,
        language="ko",
        content_hash=compute_content_hash(body),
        content_capture=ContentCapture(mode=ContentCaptureMode.FULL),
        document_type="opinion",
    )


def test_sanitize_path_component_strips_forbidden_chars() -> None:
    assert sanitize_path_component('a:b/c\\d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"
    assert sanitize_path_component("  .hidden.  ") == "hidden"
    assert sanitize_path_component("") == "untitled"


def test_path_for_document_layout() -> None:
    doc = _make_doc("본문")
    path = path_for_document(Path("/vault"), doc)
    assert path == Path(f"/vault/10_Sources/Telegram/allbareun/2026/2026-07-24-{doc.id}.md")


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    doc = _make_doc("본문 내용입니다")
    body = "## 원문\n\n본문 내용입니다\n"
    written_path = write_document(tmp_path, doc, body)
    assert written_path.exists()

    read_doc, read_body = read_document(written_path)
    assert read_doc == doc
    assert read_body == body


def test_write_then_read_round_trip_preserves_source_specific_id(tmp_path: Path) -> None:
    doc = _make_doc("본문 내용입니다", doc_id="withspecificid", source_specific_id="msg-42")
    body = "## 원문\n\n본문 내용입니다\n"
    written_path = write_document(tmp_path, doc, body)

    read_doc, _ = read_document(written_path)
    assert read_doc == doc
    assert read_doc.source_specific_id == "msg-42"


def test_write_is_idempotent_when_hash_unchanged(tmp_path: Path) -> None:
    doc = _make_doc("본문")
    path_a = write_document(tmp_path, doc, "## 원문\n\n본문\n")
    mtime_a = path_a.stat().st_mtime_ns
    path_b = write_document(tmp_path, doc, "## 원문\n\n본문\n")
    assert path_a == path_b
    assert path_b.stat().st_mtime_ns == mtime_a


def test_write_overwrites_when_hash_changes(tmp_path: Path) -> None:
    doc = _make_doc("본문", doc_id="fixedid1234567890")
    write_document(tmp_path, doc, "## 원문\n\n본문\n")

    updated_body = "본문 수정됨"
    updated_doc = doc.model_copy(update={"content_hash": compute_content_hash(updated_body)})
    write_document(tmp_path, updated_doc, f"## 원문\n\n{updated_body}\n")

    read_doc, read_body = read_document(path_for_document(tmp_path, doc))
    assert read_doc.content_hash == compute_content_hash(updated_body)
    assert updated_body in read_body


def test_list_documents_finds_all_written_files(tmp_path: Path) -> None:
    write_document(tmp_path, _make_doc("첫번째", doc_id="doc1"), "## 원문\n\n첫번째\n")
    write_document(tmp_path, _make_doc("두번째", doc_id="doc2"), "## 원문\n\n두번째\n")
    assert len(list_documents(tmp_path)) == 2


def test_round_trip_preserves_leading_blank_lines_in_body(tmp_path: Path) -> None:
    doc = _make_doc("본문", doc_id="leadingblanklines")
    body = "\n\n## 원문\n\n본문\n"
    written_path = write_document(tmp_path, doc, body)

    read_doc, read_body = read_document(written_path)
    assert read_doc == doc
    assert read_body == body


def test_path_for_document_sanitizes_malicious_id(tmp_path: Path) -> None:
    # 8 "../" segments: enough to climb past the 5 directory levels between
    # vault_path and the filename (10_Sources/<type>/<source_name>/<year>/<filename>,
    # with one more absorbed by the "date_str-" prefix having no separator before
    # the id) and land genuinely outside the vault if `doc.id` were used unsanitized.
    doc_id = "../../../../../../../etc/passwd"
    doc = _make_doc("본문", doc_id=doc_id)

    date_str = f"{doc.published_at:%Y-%m-%d}"

    # Manually reconstruct what the OLD, unfixed `path_for_document` would have
    # produced (i.e. `filename = f"{date_str}-{doc.id}.md"` with no
    # sanitize_path_component call), joined the same way the real function joins
    # its other path segments. This does NOT call into the fixed implementation.
    unfixed_filename = f"{date_str}-{doc_id}.md"
    unfixed_path = tmp_path / "10_Sources" / "Telegram" / "allbareun" / "2026" / unfixed_filename
    unfixed_resolved = unfixed_path.resolve()
    vault_resolved = tmp_path.resolve()

    # Sanity check: prove the payload is a genuine attack for this construction -
    # absent the fix, it actually escapes the vault directory.
    assert vault_resolved not in unfixed_resolved.parents

    # The real, fixed path_for_document must defeat the same payload and stay
    # confined to the vault.
    path = path_for_document(tmp_path, doc)
    resolved = path.resolve()
    assert vault_resolved in resolved.parents

    # Tighter signal than "somewhere under vault_path": the sanitized filename
    # must land in exactly the expected directory, proving containment rather
    # than merely non-escape.
    expected_dir = (tmp_path / "10_Sources" / "Telegram" / "allbareun" / "2026").resolve()
    assert resolved.parent == expected_dir

    assert "/" not in path.name

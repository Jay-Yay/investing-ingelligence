from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import httpx
import respx

from investor_intel.collectors.dart_client import DartClient
from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import ContentCapture, SourceDocument
from investor_intel.pipeline.refetch import (
    collector_source_ids,
    plan_refetch,
    refetch_dart_documents,
    rewind_checkpoints,
)
from investor_intel.storage.obsidian_repo import read_document, write_document
from investor_intel.storage.sqlite_index import connect, init_db, upsert_document

_API_KEY = "test-key"
_RCEPT = "20220516002594"
_URL = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={_API_KEY}&rcept_no={_RCEPT}"


def _doc(doc_id: str, *, source_type: SourceType = SourceType.DART, capture: str = "full",
         readable: float = 1.0, truncated: bool = False,
         accession: str | None = _RCEPT) -> SourceDocument:
    return SourceDocument(
        id=doc_id, source_type=source_type, source_name="278470", author="에이피알",
        title="에이피알 분기보고서 (2022.03)",
        source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + (accession or ""),
        source_specific_id=accession,
        published_at=datetime(2022, 5, 16, tzinfo=UTC),
        collected_at=datetime(2026, 7, 26, tzinfo=UTC),
        language="ko", content_hash=f"h-{doc_id}",
        content_capture=ContentCapture(
            mode=ContentCaptureMode(capture),
            reason=None if capture == "full" else "본문 미확보",
        ),
        companies=["278470"], document_type="dart_filing",
        filing_type="분기보고서 (2022.03)", accession_number=accession,
        readable_ratio=readable, truncated=truncated,
    )


def _seed(tmp_path: Path, docs_and_bodies) -> tuple:
    vault = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    for doc, body in docs_and_bodies:
        path = write_document(vault, doc, body)
        upsert_document(conn, doc, file_path=str(path.relative_to(vault)))
    return vault, conn


def _zip(xml: str, encoding: str = "cp949") -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{_RCEPT}.xml", xml.encode(encoding))
    return buffer.getvalue()


# --- 대상 고르기 -------------------------------------------------------------------------


def test_plan_selects_documents_by_reason(tmp_path: Path) -> None:
    _, conn = _seed(tmp_path, [
        (_doc("ok"), "정상 본문"),
        (_doc("stub", capture="metadata_only"), "본문 없음"),
        (_doc("corrupt", readable=0.5), "깨진 본문"),
        (_doc("cut", truncated=True), "잘린 본문"),
    ])
    assert {t.doc_id for t in plan_refetch(conn, reasons=("stub",)).targets} == {"stub"}
    assert {t.doc_id for t in plan_refetch(conn, reasons=("corrupt",)).targets} == {"corrupt"}
    assert {t.doc_id for t in plan_refetch(conn, reasons=("truncated",)).targets} == {"cut"}
    assert len(plan_refetch(conn).targets) == 3
    conn.close()


def test_plan_can_narrow_to_one_source_type(tmp_path: Path) -> None:
    _, conn = _seed(tmp_path, [
        (_doc("dart-stub", capture="metadata_only"), "x"),
        (_doc("sec-stub", source_type=SourceType.SEC_FILING, capture="metadata_only"), "x"),
    ])
    plan = plan_refetch(conn, source_types=["sec_filing"])
    assert {t.doc_id for t in plan.targets} == {"sec-stub"}
    conn.close()


def test_plan_splits_in_place_refetch_from_checkpoint_rewind(tmp_path: Path) -> None:
    """DART는 접수번호만으로 원문을 다시 받을 수 있고, SEC는 수집기 로직 전체가 필요하다."""
    _, conn = _seed(tmp_path, [
        (_doc("dart-stub", capture="metadata_only"), "x"),
        (_doc("sec-stub", source_type=SourceType.SEC_FILING, capture="metadata_only"), "x"),
    ])
    plan = plan_refetch(conn)
    assert {t.doc_id for t in plan.in_place()} == {"dart-stub"}
    assert {t.doc_id for t in plan.needs_rewind()} == {"sec-stub"}
    conn.close()


def test_plan_respects_the_limit(tmp_path: Path) -> None:
    _, conn = _seed(tmp_path, [
        (_doc(f"stub-{i}", capture="metadata_only", accession=f"2022051600{i}"), "x")
        for i in range(5)
    ])
    assert len(plan_refetch(conn, limit=2).targets) == 2
    conn.close()


# --- DART 제자리 재수집 ------------------------------------------------------------------


@respx.mock
def test_dry_run_reports_what_would_change_without_writing(tmp_path: Path) -> None:
    vault, conn = _seed(tmp_path, [(_doc("corrupt", readable=0.5), "�" * 50)])
    respx.get(_URL).mock(return_value=httpx.Response(
        200, content=_zip("<DOCUMENT><P>주식회사 에이피알 분기보고서 본문</P></DOCUMENT>")))
    before = sorted(p.read_text(encoding="utf-8") for p in vault.rglob("*.md"))

    client = DartClient(api_key=_API_KEY)
    result = refetch_dart_documents(
        plan_refetch(conn).targets, vault, conn, client, _API_KEY, apply=False)
    client.close()
    conn.close()

    assert result.attempted == 1 and result.updated == 1
    assert sorted(p.read_text(encoding="utf-8") for p in vault.rglob("*.md")) == before


@respx.mock
def test_apply_replaces_the_body_and_lifts_the_readable_ratio(tmp_path: Path) -> None:
    """인코딩 손상 211건의 실제 조치 경로. 디코딩 수정이 선행됐으므로 이제 제대로 들어온다."""
    vault, conn = _seed(tmp_path, [(_doc("corrupt", readable=0.5), "�" * 200)])
    respx.get(_URL).mock(return_value=httpx.Response(
        200, content=_zip("<DOCUMENT><P>주식회사 에이피알 분기보고서 본문입니다</P></DOCUMENT>")))

    client = DartClient(api_key=_API_KEY)
    result = refetch_dart_documents(
        plan_refetch(conn).targets, vault, conn, client, _API_KEY, apply=True)
    client.close()

    assert result.updated == 1
    assert result.readable_before < result.readable_after == 1.0

    (path,) = list(vault.rglob("*.md"))
    doc, body = read_document(path)
    assert "주식회사 에이피알" in body
    assert "�" not in body
    assert doc.readable_ratio == 1.0
    assert doc.content_capture.mode == ContentCaptureMode.FULL
    # 본문이 바뀌었으니 기존 분석 결과는 낡았다.
    assert doc.llm_processed is False
    assert doc.updated_at is not None

    row = conn.execute("SELECT readable_ratio, capture_mode FROM documents").fetchone()
    assert row["readable_ratio"] == 1.0 and row["capture_mode"] == "full"
    conn.close()


@respx.mock
def test_refetch_keeps_the_document_in_the_same_file(tmp_path: Path) -> None:
    """경로가 바뀌면 같은 문서의 사본이 하나 더 생긴다(파일명이 published_at으로 만들어진다)."""
    vault, conn = _seed(tmp_path, [(_doc("stub", capture="metadata_only"), "본문 미제공")])
    respx.get(_URL).mock(return_value=httpx.Response(
        200, content=_zip("<DOCUMENT><P>확보된 본문</P></DOCUMENT>")))
    (before,) = list(vault.rglob("*.md"))

    client = DartClient(api_key=_API_KEY)
    refetch_dart_documents(
        plan_refetch(conn).targets, vault, conn, client, _API_KEY, apply=True)
    client.close()
    conn.close()

    paths = list(vault.rglob("*.md"))
    assert paths == [before]


@respx.mock
def test_unchanged_content_is_not_rewritten(tmp_path: Path) -> None:
    """원문을 다시 받아도 내용이 같으면 건드리지 않는다 - 헛된 커밋을 만들지 않는다."""
    vault, conn = _seed(tmp_path, [(_doc("stub", capture="metadata_only"), "본문 미제공")])
    respx.get(_URL).mock(return_value=httpx.Response(
        200, content=_zip("<DOCUMENT><P>본문</P></DOCUMENT>")))
    client = DartClient(api_key=_API_KEY)
    targets = plan_refetch(conn).targets
    refetch_dart_documents(targets, vault, conn, client, _API_KEY, apply=True)

    # 두 번째 시도: 이미 같은 본문이 들어가 있다.
    again = refetch_dart_documents(
        plan_refetch(conn, reasons=("stub", "corrupt", "truncated")).targets
        or targets, vault, conn, client, _API_KEY, apply=True)
    client.close()
    conn.close()
    assert again.updated == 0


@respx.mock
def test_a_failed_fetch_leaves_the_document_alone(tmp_path: Path) -> None:
    vault, conn = _seed(tmp_path, [(_doc("stub", capture="metadata_only"), "본문 미제공")])
    respx.get(_URL).mock(return_value=httpx.Response(500))
    client = DartClient(api_key=_API_KEY)
    result = refetch_dart_documents(
        plan_refetch(conn).targets, vault, conn, client, _API_KEY, apply=True)
    client.close()

    assert result.failed == 1 and result.updated == 0
    doc, _ = read_document(next(iter(vault.rglob("*.md"))))
    assert doc.content_capture.mode == ContentCaptureMode.METADATA_ONLY
    conn.close()


def test_documents_without_an_accession_number_are_reported_not_skipped_silently(
    tmp_path: Path,
) -> None:
    vault, conn = _seed(tmp_path, [
        (_doc("no-acc", capture="metadata_only", accession=None), "본문 미제공")
    ])
    client = DartClient(api_key=_API_KEY)
    result = refetch_dart_documents(
        plan_refetch(conn).targets, vault, conn, client, _API_KEY, apply=True)
    client.close()
    conn.close()
    assert result.failed == 1
    assert "접수번호" in result.errors[0]


# --- 체크포인트 되감기 -------------------------------------------------------------------


def test_rewind_clears_the_checkpoint_so_backfill_revisits_history(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    conn.execute(
        "INSERT INTO collector_state (source_id, last_seen_id, last_accession_number, "
        "backfill_completed) VALUES ('sec_filing_NBIS', 'last-1', 'acc-1', 1)")
    conn.commit()

    rewind_checkpoints(conn, ["sec_filing_NBIS"], apply=True)
    row = conn.execute("SELECT * FROM collector_state").fetchone()
    conn.close()
    assert row["last_seen_id"] is None
    assert row["last_accession_number"] is None
    assert row["backfill_completed"] == 0


def test_rewind_dry_run_changes_nothing(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    conn.execute(
        "INSERT INTO collector_state (source_id, last_seen_id, backfill_completed) "
        "VALUES ('sec_filing_NBIS', 'last-1', 1)")
    conn.commit()

    assert rewind_checkpoints(conn, ["sec_filing_NBIS"], apply=False) == 1
    row = conn.execute("SELECT * FROM collector_state").fetchone()
    conn.close()
    assert row["last_seen_id"] == "last-1"


def test_source_ids_are_reconstructed_from_the_catalog(tmp_path: Path) -> None:
    _, conn = _seed(tmp_path, [
        (_doc("a", source_type=SourceType.SEC_FILING, capture="metadata_only"), "x"),
    ])
    plan = plan_refetch(conn)
    conn.close()
    assert collector_source_ids(plan.needs_rewind()) == ["sec_filing_278470"]

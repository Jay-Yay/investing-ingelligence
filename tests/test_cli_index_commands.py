from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from investor_intel.cli import app
from investor_intel.knowledge.schema import Concept, Period, Provenance
from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import ContentCapture, SourceDocument
from investor_intel.storage.obsidian_repo import write_document

runner = CliRunner()


def _doc(doc_id: str, *, readable: float = 1.0, capture: str = "full") -> SourceDocument:
    return SourceDocument(
        id=doc_id, source_type=SourceType.TELEGRAM, source_name="ch",
        source_url=f"https://t.me/ch/{doc_id}", source_specific_id=doc_id,
        published_at=datetime(2026, 7, 8, tzinfo=UTC),
        collected_at=datetime(2026, 7, 8, tzinfo=UTC),
        language="ko", content_hash=f"h-{doc_id}",
        content_capture=ContentCapture(
            mode=ContentCaptureMode(capture),
            reason=None if capture == "full" else "본문 미확보",
        ),
        document_type="opinion", readable_ratio=readable,
    )


def _vault_with_bundle(tmp_path: Path, *, body: str = "본문 내용입니다") -> Path:
    vault = tmp_path / "vault"
    write_document(vault, _doc("doc-a"), body)
    path = vault / "20_Knowledge" / "commentary" / "c-a.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        Concept(
            type="MarketCommentary", title="제목", description="요약", key="c-a",
            folder="commentary", period=Period(published="2026-07-08"),
            provenance=Provenance(system="telegram", native_id="", collected_at="",
                                  content_hash="doc-a", source_path=""),
            body=body,
        ).render(),
        encoding="utf-8",
    )
    return vault


def test_index_build_then_update_is_a_noop(tmp_path: Path) -> None:
    vault = _vault_with_bundle(tmp_path)
    search_db = tmp_path / "search.sqlite3"

    built = runner.invoke(app, ["index", "build", "--vault-path", str(vault),
                                "--search-db", str(search_db)])
    assert built.exit_code == 0, built.output
    assert "문서 1" in built.output

    updated = runner.invoke(app, ["index", "update", "--vault-path", str(vault),
                                  "--search-db", str(search_db)])
    assert updated.exit_code == 0, updated.output
    assert "추가 0 / 갱신 0 / 삭제 0" in updated.output


def test_index_build_without_a_bundle_tells_you_what_to_run(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "10_Sources").mkdir(parents=True)
    result = runner.invoke(app, ["index", "build", "--vault-path", str(vault),
                                 "--search-db", str(tmp_path / "s.sqlite3")])
    assert result.exit_code == 1
    assert "build_knowledge_bundle" in result.output


def test_index_status_reports_quality_and_lag(tmp_path: Path) -> None:
    vault = _vault_with_bundle(tmp_path)
    sqlite_path = tmp_path / "index.sqlite3"
    runner.invoke(app, ["reindex", "--vault-path", str(vault),
                        "--sqlite-path", str(sqlite_path)])

    result = runner.invoke(app, ["index", "status", "--sqlite-path", str(sqlite_path),
                                 "--search-db", str(tmp_path / "absent.sqlite3")])
    assert result.exit_code == 0, result.output
    assert "수집 문서 1건" in result.output
    assert "검색 인덱스 없음" in result.output
    assert "색인 안 된 문서 1건" in result.output


def test_index_status_gate_fails_on_corrupt_documents(tmp_path: Path) -> None:
    """`reindex`가 본문에서 품질을 직접 재므로, frontmatter를 손대지 않아도 게이트가 동작한다."""
    vault = _vault_with_bundle(tmp_path, body="�" * 200)
    sqlite_path = tmp_path / "index.sqlite3"
    runner.invoke(app, ["reindex", "--vault-path", str(vault),
                        "--sqlite-path", str(sqlite_path)])

    result = runner.invoke(app, ["index", "status", "--sqlite-path", str(sqlite_path),
                                 "--search-db", str(tmp_path / "absent.sqlite3"),
                                 "--max-corrupt", "0"])
    assert result.exit_code == 1
    assert "[FAIL]" in result.output
    assert "refetch" in result.output


def test_index_status_without_thresholds_never_fails(tmp_path: Path) -> None:
    vault = _vault_with_bundle(tmp_path, body="�" * 200)
    sqlite_path = tmp_path / "index.sqlite3"
    runner.invoke(app, ["reindex", "--vault-path", str(vault),
                        "--sqlite-path", str(sqlite_path)])
    result = runner.invoke(app, ["index", "status", "--sqlite-path", str(sqlite_path),
                                 "--search-db", str(tmp_path / "absent.sqlite3")])
    assert result.exit_code == 0


def test_refetch_dry_run_reports_targets_without_touching_anything(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_document(vault, _doc("stub-1", capture="metadata_only"), "본문 미제공")
    sqlite_path = tmp_path / "index.sqlite3"
    runner.invoke(app, ["reindex", "--vault-path", str(vault),
                        "--sqlite-path", str(sqlite_path)])
    before = sorted(p.read_text(encoding="utf-8") for p in vault.rglob("*.md"))

    result = runner.invoke(app, ["refetch", "--vault-path", str(vault),
                                 "--sqlite-path", str(sqlite_path), "--reason", "stub"])
    assert result.exit_code == 0, result.output
    assert "재수집 대상 1건" in result.output
    assert "체크포인트 되감기" in result.output
    assert sorted(p.read_text(encoding="utf-8") for p in vault.rglob("*.md")) == before


def test_refetch_rejects_an_unknown_reason(tmp_path: Path) -> None:
    result = runner.invoke(app, ["refetch", "--vault-path", str(tmp_path),
                                 "--sqlite-path", str(tmp_path / "i.sqlite3"),
                                 "--reason", "nonsense"])
    assert result.exit_code != 0


def test_refetch_says_so_when_there_is_nothing_to_do(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_document(vault, _doc("ok"), "정상 본문")
    sqlite_path = tmp_path / "index.sqlite3"
    runner.invoke(app, ["reindex", "--vault-path", str(vault),
                        "--sqlite-path", str(sqlite_path)])
    result = runner.invoke(app, ["refetch", "--vault-path", str(vault),
                                 "--sqlite-path", str(sqlite_path)])
    assert result.exit_code == 0
    assert "재수집 대상이 없다" in result.output

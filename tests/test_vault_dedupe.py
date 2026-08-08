from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from investor_intel.cli import app
from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import ContentCapture, SourceDocument
from investor_intel.storage.content_hash import compute_content_hash
from investor_intel.storage.obsidian_repo import write_document, write_document_at
from investor_intel.storage.sqlite_index import connect, init_db, upsert_document
from investor_intel.storage.vault_dedupe import apply_dedupe, plan_dedupe

runner = CliRunner()

_BODY = "## 원문\n\n본문\n"
_ANALYZED_BODY = "## 원문\n\n본문\n\n## 핵심 주장\n\n- 금리 인하 신호 (bullish, 확신도: high)\n"


def _doc(
    doc_id: str = "abc123",
    published_at: datetime = datetime(2026, 8, 1, tzinfo=UTC),
    source_name: str = "boj",
    body: str = _BODY,
) -> SourceDocument:
    return SourceDocument(
        id=doc_id,
        source_type=SourceType.CENTRAL_BANK,
        source_name=source_name,
        source_url="https://example.com/boj/minutes",
        published_at=published_at,
        collected_at=published_at,
        language="ja",
        content_hash=compute_content_hash(body),
        content_capture=ContentCapture(mode=ContentCaptureMode.FULL),
        document_type="central_bank_statement",
    )


def _write(vault: Path, conn, doc: SourceDocument, body: str = _BODY, index: bool = True) -> Path:
    path = write_document(vault, doc, body)
    if index:
        upsert_document(conn, doc, file_path=str(path.relative_to(vault)))
    return path


def _setup(tmp_path: Path):
    vault = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    return vault, conn


def test_plan_keeps_the_copy_the_index_points_at(tmp_path: Path) -> None:
    """published_at 드리프트로 같은 폴더에 쌓인 사본은 DB가 가리키는 것만 남긴다."""
    vault, conn = _setup(tmp_path)
    stale = _write(vault, conn, _doc(published_at=datetime(2026, 8, 1, tzinfo=UTC)), index=False)
    indexed = _write(vault, conn, _doc(published_at=datetime(2026, 8, 5, tzinfo=UTC)))

    report = plan_dedupe(vault, conn)

    assert [group.keep for group in report.groups] == [indexed]
    assert [group.remove for group in report.groups] == [[stale]]
    assert report.repointed == []
    assert report.freed_bytes > 0


def test_apply_removes_duplicates_and_leaves_one_file(tmp_path: Path) -> None:
    vault, conn = _setup(tmp_path)
    for day in (1, 3, 5):
        _write(vault, conn, _doc(published_at=datetime(2026, 8, day, tzinfo=UTC)))

    report = apply_dedupe(vault, conn, plan_dedupe(vault, conn))

    assert len(report.removed) == 2
    remaining = list(vault.rglob("*.md"))
    assert len(remaining) == 1
    assert remaining[0].name == "2026-08-05-abc123.md"


def test_cross_directory_copies_are_deduped_and_index_is_repointed(tmp_path: Path) -> None:
    """content_hash 중복 판정으로 id를 재사용하면 새 컬렉터의 source_name 폴더에 사본이
    생겼다(IB/naver ↔ IB/naver-weekly-hot). DB가 가리키지 않는 쪽을 지우고 경로를 맞춘다."""
    vault, conn = _setup(tmp_path)
    original = _write(vault, conn, _doc(source_name="naver"))
    copy = _write(vault, conn, _doc(source_name="naver-weekly-hot"), index=False)
    # DB에는 둘 다 아닌 경로가 들어 있는 상태(파일이 옮겨졌거나 인덱스가 낡은 경우).
    conn.execute("UPDATE documents SET file_path = ? WHERE id = ?", ("사라진/경로.md", "abc123"))
    conn.commit()

    report = apply_dedupe(vault, conn, plan_dedupe(vault, conn))

    assert report.repointed == ["abc123"]
    survivors = list(vault.rglob("*.md"))
    assert len(survivors) == 1
    assert survivors[0] in (original, copy)
    row = conn.execute("SELECT file_path FROM documents WHERE id = 'abc123'").fetchone()
    assert (vault / row["file_path"]).exists()
    # 사본을 다 지워 빈 껍데기만 남은 소스 폴더는 치운다.
    assert (
        not (vault / "10_Sources" / "CentralBank" / "naver-weekly-hot").exists()
        or not (vault / "10_Sources" / "CentralBank" / "naver").exists()
    )


def test_analyzed_copy_wins_over_the_indexed_one(tmp_path: Path) -> None:
    """분석 결과는 LLM 비용을 들여 만든 것이라, DB가 미분석 사본을 가리키고 있어도
    분석된 사본을 남기고 DB 경로를 그쪽으로 고친다."""
    vault, conn = _setup(tmp_path)
    analyzed_doc = _doc(published_at=datetime(2026, 8, 1, tzinfo=UTC))
    analyzed_path = write_document(vault, analyzed_doc, _ANALYZED_BODY)
    _write(vault, conn, _doc(published_at=datetime(2026, 8, 5, tzinfo=UTC)))

    report = apply_dedupe(vault, conn, plan_dedupe(vault, conn))

    assert report.protected == []
    assert report.repointed == ["abc123"]
    survivors = list(vault.rglob("*.md"))
    assert survivors == [analyzed_path]
    row = conn.execute("SELECT file_path FROM documents WHERE id = 'abc123'").fetchone()
    assert (vault / row["file_path"]) == analyzed_path


def test_conflicting_analyses_are_left_alone(tmp_path: Path) -> None:
    """분석 결과가 서로 다른 사본이 여러 벌이면 무엇을 버릴지 정할 수 없으니 손대지 않는다."""
    vault, conn = _setup(tmp_path)
    write_document(vault, _doc(published_at=datetime(2026, 8, 1, tzinfo=UTC)), _ANALYZED_BODY)
    _write(
        vault,
        conn,
        _doc(published_at=datetime(2026, 8, 5, tzinfo=UTC)),
        body=_ANALYZED_BODY + "\n- 추가 주장 (bearish, 확신도: low)\n",
    )

    report = plan_dedupe(vault, conn)

    assert report.groups == []
    assert report.protected == ["abc123"]

    apply_dedupe(vault, conn, report)
    assert len(list(vault.rglob("*.md"))) == 2


def test_analyzed_keep_copy_is_not_blocked(tmp_path: Path) -> None:
    """남길 사본 쪽에 분석 결과가 있으면 정상적으로 나머지를 지운다."""
    vault, conn = _setup(tmp_path)
    _write(vault, conn, _doc(published_at=datetime(2026, 8, 1, tzinfo=UTC)), index=False)
    keep_doc = _doc(published_at=datetime(2026, 8, 5, tzinfo=UTC))
    keep_path = write_document(vault, keep_doc, _ANALYZED_BODY)
    upsert_document(conn, keep_doc, file_path=str(keep_path.relative_to(vault)))

    report = apply_dedupe(vault, conn, plan_dedupe(vault, conn))

    assert len(report.removed) == 1
    assert keep_path.exists()


def test_distinct_documents_are_left_alone(tmp_path: Path) -> None:
    vault, conn = _setup(tmp_path)
    _write(vault, conn, _doc(doc_id="aaa111"))
    _write(vault, conn, _doc(doc_id="bbb222"))

    report = plan_dedupe(vault, conn)

    assert report.groups == []
    assert len(list(vault.rglob("*.md"))) == 2


def test_unparsable_file_is_reported_not_deleted(tmp_path: Path) -> None:
    vault, conn = _setup(tmp_path)
    kept = _write(vault, conn, _doc(published_at=datetime(2026, 8, 5, tzinfo=UTC)))
    broken = kept.parent / "2026-08-01-abc123.md"
    broken.write_text("frontmatter 없음", encoding="utf-8")

    report = plan_dedupe(vault, conn)

    assert [path for path, _ in report.unparsed] == [broken]
    assert report.groups == []
    apply_dedupe(vault, conn, report)
    assert broken.exists()


def test_cli_dry_run_does_not_delete_anything(tmp_path: Path) -> None:
    vault, conn = _setup(tmp_path)
    conn.close()
    sqlite_path = tmp_path / "index.sqlite3"
    conn = connect(sqlite_path)
    init_db(conn)
    for day in (1, 5):
        _write(vault, conn, _doc(published_at=datetime(2026, 8, day, tzinfo=UTC)))
    conn.close()

    result = runner.invoke(
        app, ["dedupe-vault", "--vault-path", str(vault), "--sqlite-path", str(sqlite_path)]
    )

    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output
    assert len(list(vault.rglob("*.md"))) == 2

    applied = runner.invoke(
        app,
        [
            "dedupe-vault",
            "--vault-path",
            str(vault),
            "--sqlite-path",
            str(sqlite_path),
            "--apply",
        ],
    )
    assert applied.exit_code == 0, applied.output
    assert len(list(vault.rglob("*.md"))) == 1


def test_in_place_rewrite_keeps_a_single_file(tmp_path: Path) -> None:
    """write_document_at은 경로를 바꾸지 않으므로 사본이 늘지 않는다(수집 쪽 재발 방지)."""
    vault, conn = _setup(tmp_path)
    path = _write(vault, conn, _doc(published_at=datetime(2026, 8, 1, tzinfo=UTC)))

    updated = _doc(published_at=datetime(2026, 8, 5, tzinfo=UTC), body="바뀐 본문")
    rewritten = write_document_at(path, updated, "## 원문\n\n바뀐 본문\n")

    assert rewritten == path
    assert len(list(vault.rglob("*.md"))) == 1

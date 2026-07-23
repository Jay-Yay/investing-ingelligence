from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from investor_intel.cli import app
from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import ContentCapture, SourceDocument
from investor_intel.storage.content_hash import compute_content_hash, compute_stable_id
from investor_intel.storage.obsidian_repo import write_document
from investor_intel.storage.sqlite_index import connect

runner = CliRunner()


def _make_doc(n: int) -> SourceDocument:
    now = datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)
    body = f"본문 {n}"
    return SourceDocument(
        id=compute_stable_id("telegram", "allbareun", str(n), f"https://t.me/allbareun/{n}"),
        source_type=SourceType.TELEGRAM,
        source_name="allbareun",
        source_url=f"https://t.me/allbareun/{n}",
        published_at=now,
        collected_at=now,
        language="ko",
        content_hash=compute_content_hash(body),
        content_capture=ContentCapture(mode=ContentCaptureMode.FULL),
        document_type="opinion",
    )


def test_reindex_rebuilds_sqlite_from_markdown(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    for n in (1, 2):
        write_document(vault, _make_doc(n), f"## 원문\n\n본문 {n}\n")

    sqlite_path = tmp_path / "data" / "index.sqlite3"
    result = runner.invoke(
        app, ["reindex", "--vault-path", str(vault), "--sqlite-path", str(sqlite_path)]
    )
    assert result.exit_code == 0, result.output

    conn = connect(sqlite_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
        assert count == 2
    finally:
        conn.close()


def test_reindex_command_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_document(vault, _make_doc(1), "## 원문\n\n본문 1\n")
    sqlite_path = tmp_path / "data" / "index.sqlite3"

    runner.invoke(app, ["reindex", "--vault-path", str(vault), "--sqlite-path", str(sqlite_path)])
    runner.invoke(app, ["reindex", "--vault-path", str(vault), "--sqlite-path", str(sqlite_path)])

    conn = connect(sqlite_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
        assert count == 1
    finally:
        conn.close()

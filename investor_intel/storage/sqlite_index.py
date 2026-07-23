from __future__ import annotations

import sqlite3
from pathlib import Path

from investor_intel.models.source_document import SourceDocument
from investor_intel.storage.obsidian_repo import list_documents, read_document

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
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
);

CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_canonical_url ON documents(canonical_url);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_type, source_name);

CREATE TABLE IF NOT EXISTS document_assets (
    document_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    asset_type TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_document_assets_ticker ON document_assets(ticker);

CREATE TABLE IF NOT EXISTS collector_state (
    source_id TEXT PRIMARY KEY,
    last_success_at TEXT,
    last_seen_id TEXT,
    last_accession_number TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    backfill_completed INTEGER NOT NULL DEFAULT 0
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def upsert_document(
    conn: sqlite3.Connection,
    doc: SourceDocument,
    file_path: str,
    source_specific_id: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO documents (
            id, source_type, source_name, source_specific_id, canonical_url,
            title, author, published_at, collected_at, content_hash,
            document_type, filing_type, accession_number, llm_processed, file_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            source_type=excluded.source_type,
            source_name=excluded.source_name,
            source_specific_id=excluded.source_specific_id,
            canonical_url=excluded.canonical_url,
            title=excluded.title,
            author=excluded.author,
            published_at=excluded.published_at,
            collected_at=excluded.collected_at,
            content_hash=excluded.content_hash,
            document_type=excluded.document_type,
            filing_type=excluded.filing_type,
            accession_number=excluded.accession_number,
            llm_processed=excluded.llm_processed,
            file_path=excluded.file_path
        """,
        (
            doc.id,
            doc.source_type.value,
            doc.source_name,
            source_specific_id,
            doc.source_url,
            doc.title,
            doc.author,
            doc.published_at.isoformat(),
            doc.collected_at.isoformat(),
            doc.content_hash,
            doc.document_type,
            doc.filing_type,
            doc.accession_number,
            int(doc.llm_processed),
            file_path,
        ),
    )
    conn.execute("DELETE FROM document_assets WHERE document_id = ?", (doc.id,))
    for asset in doc.assets:
        conn.execute(
            "INSERT INTO document_assets (document_id, ticker, asset_type) VALUES (?, ?, ?)",
            (doc.id, asset.ticker, asset.asset_type),
        )
    conn.commit()


def get_document_by_id(conn: sqlite3.Connection, doc_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()


def find_duplicate(
    conn: sqlite3.Connection,
    source_type: str,
    source_name: str,
    source_specific_id: str | None,
    canonical_url: str,
    content_hash: str,
    title: str | None,
    author: str | None,
    published_at: str,
) -> str | None:
    if source_specific_id:
        row = conn.execute(
            "SELECT id FROM documents WHERE source_type = ? AND source_name = ? "
            "AND source_specific_id = ?",
            (source_type, source_name, source_specific_id),
        ).fetchone()
        if row:
            return str(row["id"])

    row = conn.execute(
        "SELECT id FROM documents WHERE canonical_url = ?", (canonical_url,)
    ).fetchone()
    if row:
        return str(row["id"])

    row = conn.execute(
        "SELECT id FROM documents WHERE content_hash = ?", (content_hash,)
    ).fetchone()
    if row:
        return str(row["id"])

    row = conn.execute(
        "SELECT id FROM documents WHERE title IS ? AND author IS ? AND published_at = ?",
        (title, author, published_at),
    ).fetchone()
    if row:
        return str(row["id"])

    return None


def reindex(conn: sqlite3.Connection, vault_path: Path) -> int:
    conn.execute("DELETE FROM document_assets")
    conn.execute("DELETE FROM documents")
    conn.commit()
    count = 0
    for path in list_documents(vault_path):
        doc, _ = read_document(path)
        upsert_document(conn, doc, str(path.relative_to(vault_path)))
        count += 1
    return count


def get_collector_state(conn: sqlite3.Connection, source_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM collector_state WHERE source_id = ?", (source_id,)
    ).fetchone()


def save_collector_state(
    conn: sqlite3.Connection,
    source_id: str,
    last_success_at: str | None,
    last_seen_id: str | None,
    last_accession_number: str | None,
    failure_count: int,
    next_retry_at: str | None,
    backfill_completed: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO collector_state (
            source_id, last_success_at, last_seen_id, last_accession_number,
            failure_count, next_retry_at, backfill_completed
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            last_success_at=excluded.last_success_at,
            last_seen_id=excluded.last_seen_id,
            last_accession_number=excluded.last_accession_number,
            failure_count=excluded.failure_count,
            next_retry_at=excluded.next_retry_at,
            backfill_completed=excluded.backfill_completed
        """,
        (
            source_id,
            last_success_at,
            last_seen_id,
            last_accession_number,
            failure_count,
            next_retry_at,
            int(backfill_completed),
        ),
    )
    conn.commit()

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import cast

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
    reporting_period TEXT,
    is_transcript INTEGER NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS dart_corp_codes (
    corp_code TEXT PRIMARY KEY,
    corp_name TEXT NOT NULL,
    stock_code TEXT,
    modify_date TEXT
);

CREATE INDEX IF NOT EXISTS idx_dart_corp_codes_stock_code ON dart_corp_codes(stock_code);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_documents_columns(conn: sqlite3.Connection) -> None:
    """data/index.sqlite3는 vault에서 재생성 가능한 로컬 캐시라 커밋되지 않는다(Runbook.md 참고) -
    그래서 스키마를 바꿔도 데이터 마이그레이션은 필요 없지만, 이미 만들어진 옛 스키마의 sqlite
    파일이 로컬에 남아있는 머신에서는 `CREATE TABLE IF NOT EXISTS`가 컬럼을 추가해주지 않으므로
    ALTER TABLE로 보강한다. 새 컬럼을 참조하는 인덱스는 컬럼이 실제로 존재한 뒤에만 만들 수
    있어 이 함수 안에서 함께 처리한다(스키마 문자열의 CREATE INDEX보다 먼저 실행하면 옛 DB에서
    "no such column" 오류가 난다).
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(documents)")}
    if "reporting_period" not in existing:
        conn.execute("ALTER TABLE documents ADD COLUMN reporting_period TEXT")
    if "is_transcript" not in existing:
        conn.execute("ALTER TABLE documents ADD COLUMN is_transcript INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_transcript "
        "ON documents(source_name, reporting_period, is_transcript)"
    )


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    _migrate_documents_columns(conn)
    conn.commit()


def _is_transcript(document_type: str, filing_type: str | None, title: str | None) -> bool:
    """이 문서가 실적발표 컨퍼런스콜 녹취록(원문)인지 판별한다.

    두 경로가 있다: (1) 이 새 웹서치 수집기가 만든 문서(document_type이 그 자체로 표시),
    (2) 기존 SECFilingsCollector가 8-K exhibit에서 찾은 녹취록(sec_filings.py가 제목에
    "[컨퍼런스콜] " 접두어를 붙이는 것으로만 표시 - 별도 document_type 없음). 두 경로 모두
    잡아야 dedup 쿼리(has_transcript_for_period)가 "SEC 쪽에서 이미 찾았으니 웹서치 건너뛰기"를
    판단할 수 있다.
    """
    if document_type == "earnings_call_transcript":
        return True
    if document_type == "sec_filing" and filing_type == "8-K" and title is not None:
        return title.startswith("[컨퍼런스콜]")
    return False


def upsert_document(
    conn: sqlite3.Connection,
    doc: SourceDocument,
    file_path: str,
    source_specific_id: str | None = None,
) -> None:
    is_transcript = _is_transcript(doc.document_type, doc.filing_type, doc.title)
    conn.execute(
        """
        INSERT INTO documents (
            id, source_type, source_name, source_specific_id, canonical_url,
            title, author, published_at, collected_at, content_hash,
            document_type, filing_type, accession_number, reporting_period,
            is_transcript, llm_processed, file_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            reporting_period=excluded.reporting_period,
            is_transcript=excluded.is_transcript,
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
            doc.reporting_period,
            int(is_transcript),
            int(doc.llm_processed),
            file_path,
        ),
    )
    conn.execute("DELETE FROM document_assets WHERE document_id = ?", (doc.id,))
    conn.executemany(
        "INSERT INTO document_assets (document_id, ticker, asset_type) VALUES (?, ?, ?)",
        [(doc.id, ticker, asset_type) for ticker, asset_type in _asset_rows(doc)],
    )
    conn.commit()


# 관계 키는 `kr-278470` / `us-NBIS`처럼 시장 접두어를 달고 저장된다. `document_assets.ticker`는
# 티커·종목코드 그대로여야 하므로(예: `latest_filing_for_ticker`가 티커로 조회한다) 접두어를
# 떼어 넣는다.
_MARKET_PREFIX = re.compile(r"^(?:kr|us)-")


def _asset_rows(doc: SourceDocument) -> list[tuple[str, str]]:
    """이 문서로부터 만들 `document_assets` 행.

    예전에는 `doc.assets`만 넣었고, 그 필드를 채우는 수집기가 하나도 없어서 테이블이 0행이었다
    - 티커로 문서를 찾는 조회가 모두 빈 결과를 냈다. 실제 종목 관계는 `companies`(수집기가
    확정한 값)와 `entities`(본문에서 복원한 값)에 있으므로 셋을 함께 넣는다.
    """
    rows: list[tuple[str, str]] = [(asset.ticker, asset.asset_type) for asset in doc.assets]
    # `entities`가 없는 옛 문서(2026-08-25 이전 수집분)는 `companies`가 유일한 관계 정보다.
    # 이 폴백이 있어야 재색인만으로 기존 4,818건의 티커 조회가 살아난다.
    mentions = doc.entities.mentions or doc.companies
    for ticker in mentions:
        rows.append((_MARKET_PREFIX.sub("", ticker), "mention"))
    for ticker in doc.entities.analyst_house:
        # 분석 주체는 분석 대상과 같은 이름표를 달면 안 된다 - 섞이면 증권사로 필터링해
        # 정답 문서를 지우게 된다.
        rows.append((_MARKET_PREFIX.sub("", ticker), "analyst_house"))
    return list(dict.fromkeys(rows))


def get_document_by_id(conn: sqlite3.Connection, doc_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()


def has_transcript_for_period(
    conn: sqlite3.Connection, ticker: str, reporting_period: str
) -> bool:
    """이 티커의 이 분기(reporting_period, ISO 날짜)에 대한 실적발표 컨퍼런스콜 녹취록이
    (SEC 8-K exhibit 경로든, 이 웹서치 컬렉터 경로든) 이미 확보돼 있는지 확인한다.

    earnings_transcript_web 파이프라인이 LLM 웹서치를 호출하기 "전"에 이 함수로 먼저 확인해,
    SECFilingsCollector가 이미 같은 분기의 진짜 녹취록을 8-K exhibit에서 찾아둔 경우 중복
    LLM 호출(비용)을 피한다.
    """
    row = conn.execute(
        "SELECT 1 FROM documents WHERE source_name = ? AND reporting_period = ? "
        "AND is_transcript = 1 LIMIT 1",
        (ticker, reporting_period),
    ).fetchone()
    return row is not None


def latest_filing_for_ticker(
    conn: sqlite3.Connection, ticker: str, filing_types: tuple[str, ...]
) -> sqlite3.Row | None:
    """이 티커의 SEC 공시(source_type='sec_filing') 중 filing_types에 속하는 가장 최근
    문서(published_at 기준) 하나를 반환한다. `regime analyze-ai`가 하이퍼스케일러/반도체
    종목의 최신 10-Q/10-K 본문을 찾아 LLM 추출 입력으로 쓰는 데 사용한다."""
    placeholders = ",".join("?" for _ in filing_types)
    row = conn.execute(
        f"""
        SELECT d.* FROM documents d
        JOIN document_assets da ON d.id = da.document_id
        WHERE da.ticker = ? AND d.source_type = 'sec_filing'
        AND d.filing_type IN ({placeholders})
        ORDER BY d.published_at DESC
        LIMIT 1
        """,
        (ticker, *filing_types),
    ).fetchone()
    return row


def get_document_by_canonical_url(
    conn: sqlite3.Connection, canonical_url: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM documents WHERE canonical_url = ?", (canonical_url,)
    ).fetchone()


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
        upsert_document(
            conn,
            doc,
            str(path.relative_to(vault_path)),
            source_specific_id=doc.source_specific_id,
        )
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


def export_collector_state(conn: sqlite3.Connection) -> dict[str, dict[str, object]]:
    rows = conn.execute("SELECT * FROM collector_state").fetchall()
    return {
        row["source_id"]: {
            "last_success_at": row["last_success_at"],
            "last_seen_id": row["last_seen_id"],
            "last_accession_number": row["last_accession_number"],
            "failure_count": row["failure_count"],
            "next_retry_at": row["next_retry_at"],
            "backfill_completed": bool(row["backfill_completed"]),
        }
        for row in rows
    }


def import_collector_state(conn: sqlite3.Connection, states: dict[str, dict[str, object]]) -> None:
    for source_id, state in states.items():
        save_collector_state(
            conn,
            source_id=source_id,
            last_success_at=cast("str | None", state.get("last_success_at")),
            last_seen_id=cast("str | None", state.get("last_seen_id")),
            last_accession_number=cast("str | None", state.get("last_accession_number")),
            failure_count=cast("int", state.get("failure_count", 0)),
            next_retry_at=cast("str | None", state.get("next_retry_at")),
            backfill_completed=bool(state.get("backfill_completed", False)),
        )


def is_dart_corp_code_cache_populated(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) AS c FROM dart_corp_codes").fetchone()
    return bool(row["c"])


def replace_dart_corp_codes(
    conn: sqlite3.Connection, entries: list[tuple[str, str, str | None, str]]
) -> None:
    """Each entry is (corp_code, corp_name, stock_code, modify_date)."""
    conn.execute("DELETE FROM dart_corp_codes")
    conn.executemany(
        "INSERT INTO dart_corp_codes (corp_code, corp_name, stock_code, modify_date) "
        "VALUES (?, ?, ?, ?)",
        entries,
    )
    conn.commit()


def find_dart_corp_code(
    conn: sqlite3.Connection, stock_code: str | None, name: str | None
) -> str | None:
    if stock_code:
        row = conn.execute(
            "SELECT corp_code FROM dart_corp_codes WHERE stock_code = ?", (stock_code,)
        ).fetchone()
        if row:
            return str(row["corp_code"])

    if name:
        row = conn.execute(
            "SELECT corp_code FROM dart_corp_codes WHERE corp_name = ?", (name,)
        ).fetchone()
        if row:
            return str(row["corp_code"])
    return None


def find_dart_company_by_stock_code(
    conn: sqlite3.Connection, stock_code: str
) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT corp_code, corp_name FROM dart_corp_codes WHERE stock_code = ?", (stock_code,)
    ).fetchone()
    if row:
        return str(row["corp_code"]), str(row["corp_name"])
    return None

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from investor_intel.indexing.tokenizer import to_fts_document, to_fts_query

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunk_meta (
    rowid_ref      INTEGER PRIMARY KEY,
    chunk_uid      TEXT UNIQUE NOT NULL,
    doc_id         TEXT NOT NULL,
    ord            INTEGER NOT NULL,
    doc_path       TEXT NOT NULL,
    source_type    TEXT NOT NULL,
    source_name    TEXT NOT NULL,
    published_at   TEXT,
    title          TEXT,
    filing_type    TEXT,
    capture_mode   TEXT,
    heading_path   TEXT,
    kind           TEXT,
    okf_type       TEXT,
    entity_key     TEXT,
    period_year    TEXT,
    pub_year       TEXT,
    okf_status     TEXT,
    n_chars        INTEGER NOT NULL,
    -- 청크에 붙인 문맥(concept의 description)을 토큰화 전 원문으로 함께 보관한다.
    -- chunk_fts.ctx는 토큰화된 형태라 되읽을 수 없다. 이 컬럼이 있어야 벡터 인덱스가
    -- 번들을 다시 파싱해 다시 청킹하지 않고 같은 청크를 그대로 쓸 수 있다 - 청킹을 두 곳에서
    -- 따로 하면 chunk_uid가 어긋나 RRF가 같은 조각을 다른 것으로 취급한다.
    ctx_text       TEXT NOT NULL DEFAULT '',
    -- 원본 vault 문서의 id. concept id와 다르다. 이게 있어야 "수집은 됐는데 색인 안 된
    -- 문서가 몇 건인가"를 카탈로그와 조인해서 정확히 셀 수 있다.
    native_doc_id  TEXT NOT NULL DEFAULT '',
    raw_text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON chunk_meta(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunk_source ON chunk_meta(source_type, published_at);
CREATE INDEX IF NOT EXISTS idx_chunk_capture ON chunk_meta(capture_mode);
"""

# 이미 만들어둔 옛 스키마의 인덱스 파일이 남아 있으면 CREATE TABLE IF NOT EXISTS는 컬럼을
# 추가해주지 않는다. 새 컬럼을 참조하는 인덱스는 컬럼이 실제로 생긴 뒤에만 만들 수 있어
# 분리해 둔다.
_OKF_COLUMNS = {"okf_type": "TEXT", "entity_key": "TEXT", "period_year": "TEXT",
                "pub_year": "TEXT", "okf_status": "TEXT",
                "ctx_text": "TEXT NOT NULL DEFAULT ''",
                "native_doc_id": "TEXT NOT NULL DEFAULT ''"}
_OKF_INDEXES = """
-- OKF 메타데이터로 '검색 전에 후보를 좁히는' 경로. 이게 있어야 지식 레이어의
-- entities/period가 실제로 검색에 쓰인다 - 없으면 OKF는 사람만 읽는 문서로 남는다.
CREATE INDEX IF NOT EXISTS idx_chunk_entity ON chunk_meta(entity_key, period_year);
CREATE INDEX IF NOT EXISTS idx_chunk_okf ON chunk_meta(okf_type, okf_status);
CREATE INDEX IF NOT EXISTS idx_chunk_native ON chunk_meta(native_doc_id);
"""

# FTS5 컬럼을 셋으로 나눈 이유: bm25()가 컬럼별 가중치를 받기 때문에, 같은 토큰이라도
# 제목/문맥헤더에서 맞았을 때와 본문에서 맞았을 때 점수를 다르게 줄 수 있다.
_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    ctx, title, body,
    tokenize = 'unicode61 remove_diacritics 0'
);
"""


@dataclass
class Hit:
    chunk_uid: str
    doc_id: str
    score: float
    source_type: str
    title: str
    heading_path: str
    text: str
    capture_mode: str
    okf_type: str = ""
    entity_key: str = ""
    period_year: str = ""
    okf_status: str = ""


@dataclass
class IndexStats:
    n_docs: int
    n_chunks: int
    n_chars_indexed: int
    build_seconds: float
    db_bytes: int


class Bm25Index:
    """SQLite FTS5(BM25) 위에 얹은 청크 인덱스.

    토큰 정의는 우리가 통제하고(tokenizer.to_fts_document), 역색인 구조와 BM25 점수
    계산은 SQLite의 검증된 구현에 맡긴다. 직접 구현한 posting list보다 빠르고,
    디스크에 그대로 남아 다음 실행에서 재사용된다.
    """

    def __init__(self, db_path: Path, korean_ngram: bool = True, metadata_boost: bool = False,
                 korean_keep_word: bool = False):
        self.db_path = Path(db_path)
        self.korean_ngram = korean_ngram
        self.korean_keep_word = korean_keep_word
        self.metadata_boost = metadata_boost
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        existing = {r[1] for r in self.conn.execute("PRAGMA table_info(chunk_meta)")}
        for col, decl in _OKF_COLUMNS.items():
            if col not in existing:
                self.conn.execute(f"ALTER TABLE chunk_meta ADD COLUMN {col} {decl}")
        self.conn.executescript(_OKF_INDEXES)
        self.conn.executescript(_FTS)

    # --- Store -------------------------------------------------------------
    def _insert(self, cur: sqlite3.Cursor, record: tuple[dict, str, str, str]) -> int:
        meta, ctx, title, body = record
        cur.execute(
            """INSERT INTO chunk_meta (chunk_uid, doc_id, ord, doc_path, source_type,
               source_name, published_at, title, filing_type, capture_mode, heading_path,
               kind, okf_type, entity_key, period_year, pub_year, okf_status, n_chars,
               ctx_text, native_doc_id, raw_text)
               VALUES (:chunk_uid,:doc_id,:ord,:doc_path,:source_type,:source_name,
               :published_at,:title,:filing_type,:capture_mode,:heading_path,:kind,
               :okf_type,:entity_key,:period_year,:pub_year,:okf_status,:n_chars,
               :ctx_text,:native_doc_id,:raw_text)""",
            {"okf_type": "", "entity_key": "", "period_year": "", "pub_year": "",
             "okf_status": "stable", "ctx_text": ctx, "native_doc_id": "", **meta},
        )
        rid = cur.lastrowid
        cur.execute(
            "INSERT INTO chunk_fts(rowid, ctx, title, body) VALUES (?,?,?,?)",
            (
                rid,
                to_fts_document(ctx, self.korean_ngram, self.korean_keep_word) if ctx else "",
                to_fts_document(title, self.korean_ngram, self.korean_keep_word) if title else "",
                to_fts_document(body, self.korean_ngram, self.korean_keep_word),
            ),
        )
        return int(meta["n_chars"])

    def build(self, records: Iterable[tuple[dict, str, str, str]]) -> IndexStats:
        """records: (meta, ctx_text, title_text, body_text). 인덱스를 통째로 다시 만든다."""
        t0 = time.time()
        cur = self.conn.cursor()
        cur.execute("DELETE FROM chunk_meta")
        cur.execute("DELETE FROM chunk_fts")
        n_chunks = n_chars = 0
        docs: set[str] = set()
        for record in records:
            n_chars += self._insert(cur, record)
            n_chunks += 1
            docs.add(record[0]["doc_id"])
        self.conn.commit()
        self.optimize()
        return IndexStats(
            n_docs=len(docs),
            n_chunks=n_chunks,
            n_chars_indexed=n_chars,
            build_seconds=round(time.time() - t0, 2),
            db_bytes=self.db_path.stat().st_size,
        )

    def upsert_document(
        self, doc_id: str, records: Iterable[tuple[dict, str, str, str]]
    ) -> tuple[int, int]:
        """한 문서의 청크를 통째로 갈아끼운다. (청크 수, 색인 글자수)를 돌려준다.

        청킹은 결정론적이라 같은 입력이면 같은 청크가 나온다. 그래서 문서 단위로 지우고
        다시 넣는 것이 안전하다 - 청크별로 비교해 부분 갱신하는 것보다 단순하고, 청크
        경계가 바뀌는 경우(본문이 조금 길어지면 뒤쪽 청크가 전부 밀린다)도 자동으로 맞는다.
        """
        cur = self.conn.cursor()
        self._delete_doc_rows(cur, doc_id)
        n_chunks = n_chars = 0
        for record in records:
            n_chars += self._insert(cur, record)
            n_chunks += 1
        self.conn.commit()
        return n_chunks, n_chars

    def delete_documents(self, doc_ids: Iterable[str]) -> int:
        cur = self.conn.cursor()
        removed = 0
        for doc_id in doc_ids:
            removed += self._delete_doc_rows(cur, doc_id)
        self.conn.commit()
        return removed

    def _delete_doc_rows(self, cur: sqlite3.Cursor, doc_id: str) -> int:
        """chunk_meta와 chunk_fts를 함께 지운다.

        chunk_fts는 외부 컨텐츠 테이블이 아니라 자기 데이터를 들고 있으므로, chunk_meta만
        지우면 FTS 쪽에 고아 행이 남아 지운 문서가 검색 결과에 계속 나온다.
        """
        rows = cur.execute(
            "SELECT rowid_ref FROM chunk_meta WHERE doc_id = ?", (doc_id,)
        ).fetchall()
        if not rows:
            return 0
        ids = [(int(r["rowid_ref"]),) for r in rows]
        cur.executemany("DELETE FROM chunk_fts WHERE rowid = ?", ids)
        cur.executemany("DELETE FROM chunk_meta WHERE rowid_ref = ?", ids)
        return len(ids)

    def indexed_native_ids(self) -> set[str]:
        """색인된 청크가 가리키는 원본 vault 문서 id 집합."""
        return {
            str(row[0])
            for row in self.conn.execute(
                "SELECT DISTINCT native_doc_id FROM chunk_meta WHERE native_doc_id != ''")
        }

    def optimize(self) -> None:
        self.conn.execute("INSERT INTO chunk_fts(chunk_fts) VALUES('optimize')")
        self.conn.commit()

    def stats(self) -> IndexStats:
        row = self.conn.execute(
            "SELECT COUNT(DISTINCT doc_id) AS docs, COUNT(*) AS chunks, "
            "COALESCE(SUM(n_chars), 0) AS chars FROM chunk_meta"
        ).fetchone()
        return IndexStats(
            n_docs=row["docs"], n_chunks=row["chunks"], n_chars_indexed=row["chars"],
            build_seconds=0.0,
            db_bytes=self.db_path.stat().st_size if self.db_path.exists() else 0,
        )

    def chunk_records(self, doc_ids: Sequence[str] | None = None) -> list[sqlite3.Row]:
        """색인된 청크를 그대로 돌려준다.

        벡터 인덱스가 번들을 다시 파싱해 다시 청킹하지 않고 이걸 쓴다. 같은 청킹을 두 곳에서
        따로 하면 `chunk_uid`가 어긋날 수 있고, 그러면 두 검색 결과를 RRF로 합칠 때 같은
        조각이 서로 다른 것으로 취급된다.
        """
        if doc_ids is None:
            return self.conn.execute(
                "SELECT * FROM chunk_meta ORDER BY doc_id, ord").fetchall()
        out: list[sqlite3.Row] = []
        for i in range(0, len(doc_ids), 500):
            batch = doc_ids[i : i + 500]
            placeholders = ",".join("?" * len(batch))
            out += self.conn.execute(
                f"SELECT * FROM chunk_meta WHERE doc_id IN ({placeholders}) ORDER BY doc_id, ord",
                list(batch),
            ).fetchall()
        return out

    # --- Retrieve ----------------------------------------------------------
    def search(
        self,
        query: str,
        k: int = 10,
        *,
        source_types: Sequence[str] | None = None,
        published_after: str | None = None,
        exclude_metadata_only: bool = False,
        entity_key: str | None = None,
        period_year: str | None = None,
        okf_types: Sequence[str] | None = None,
        exclude_status: Sequence[str] | None = None,
    ) -> list[Hit]:
        match = to_fts_query(query, self.korean_ngram, self.korean_keep_word)
        if not match:
            return []
        # bm25()는 값이 작을수록(더 음수일수록) 관련도가 높다. 컬럼 가중치는
        # (ctx, title, body) 순. metadata_boost가 꺼져 있으면 세 컬럼을 동등하게 본다.
        w = (2.0, 3.0, 1.0) if self.metadata_boost else (1.0, 1.0, 1.0)
        where = ["chunk_fts MATCH ?"]
        params: list = [match]
        if source_types:
            where.append("m.source_type IN (%s)" % ",".join("?" * len(source_types)))
            params.extend(source_types)
        if published_after:
            where.append("m.published_at >= ?")
            params.append(published_after)
        if exclude_metadata_only:
            where.append("m.capture_mode != 'metadata_only'")
        # --- OKF 메타데이터 프리필터 ---
        if entity_key:
            where.append("(m.entity_key = ? OR m.entity_key LIKE ?)")
            params.extend([entity_key, f"%|{entity_key}|%"])
        if period_year:
            # 질의의 '2026년'이 회계연도인지 제출연도인지는 사용자가 말해주지 않는다.
            # 10-K는 2026년에 제출돼도 2025 회계연도를 다룬다. 한쪽만 보면 정답이 통째로
            # 사라진다(실측: E 계열 160건 중 7건이 전부 이 이유로 소실).
            where.append("(m.period_year = ? OR m.pub_year = ?)")
            params.extend([period_year, period_year])
        if okf_types:
            where.append("m.okf_type IN (%s)" % ",".join("?" * len(okf_types)))
            params.extend(okf_types)
        if exclude_status:
            where.append("m.okf_status NOT IN (%s)" % ",".join("?" * len(exclude_status)))
            params.extend(exclude_status)
        sql = f"""
            SELECT m.*, bm25(chunk_fts, ?, ?, ?) AS score
            FROM chunk_fts JOIN chunk_meta m ON m.rowid_ref = chunk_fts.rowid
            WHERE {' AND '.join(where)}
            ORDER BY score LIMIT ?
        """
        rows = self.conn.execute(sql, [*w, *params, k]).fetchall()
        return [
            Hit(
                chunk_uid=r["chunk_uid"], doc_id=r["doc_id"], score=r["score"],
                source_type=r["source_type"], title=r["title"] or "",
                heading_path=r["heading_path"] or "", text=r["raw_text"],
                capture_mode=r["capture_mode"] or "",
            )
            for r in rows
        ]

    def search_documents(
        self,
        query: str,
        k: int = 10,
        *,
        pool: int = 300,
        top_chunks_per_doc: int = 1,
        exclude_metadata_only: bool = False,
        **filters,
    ) -> list[Hit]:
        """청크로 검색하되 결과는 문서 단위로 집계해 돌려준다.

        청크 인덱스의 약점 하나는 한 문서의 여러 청크가 상위 K를 차지해 다른 후보 문서를
        밀어낸다는 것이다(관측: 실무형 질의 24건 중 6건에서 top-10이 3개 이하 문서로 채워짐).
        또 문서 전체를 하나의 레코드로 색인하면 흩어진 질의어가 한 문서 안에서 자연히 합산되는데,
        청크 단위는 그 합산이 사라진다. 상위 청크를 문서로 묶고 문서당 상위 n개 청크 점수를
        더하면, 합산 효과는 되살리면서 반환 단위는 여전히 작은 청크로 유지할 수 있다.

        다만 실측 결과 top_chunks_per_doc를 2 이상으로 두면 '약한 매칭이 여러 개인 긴 문서'가
        '강한 매칭 하나인 짧은 문서'를 이겨서 자동 평가셋 recall@10이 0.978 -> 0.885로 떨어졌다.
        기본값을 1(=문서당 최고 청크 점수)로 두는 근거다.
        """
        wide = self.search(query, k=pool, exclude_metadata_only=exclude_metadata_only, **filters)
        by_doc: dict[str, list[Hit]] = {}
        for h in wide:
            by_doc.setdefault(h.doc_id, []).append(h)
        scored: list[tuple[float, Hit]] = []
        for hits in by_doc.values():
            hits.sort(key=lambda h: h.score)  # bm25는 작을수록 관련도 높음
            doc_score = sum(h.score for h in hits[:top_chunks_per_doc])
            best = hits[0]
            scored.append((doc_score, Hit(best.chunk_uid, best.doc_id, doc_score,
                                          best.source_type, best.title, best.heading_path,
                                          best.text, best.capture_mode, best.okf_type,
                                          best.entity_key, best.period_year, best.okf_status)))
        scored.sort(key=lambda x: x[0])
        return [h for _, h in scored[:k]]

    def close(self) -> None:
        self.conn.close()

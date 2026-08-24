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
    n_chars        INTEGER NOT NULL,
    raw_text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON chunk_meta(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunk_source ON chunk_meta(source_type, published_at);
CREATE INDEX IF NOT EXISTS idx_chunk_capture ON chunk_meta(capture_mode);
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
        self.conn.executescript(_FTS)

    # --- Store -------------------------------------------------------------
    def build(self, records: Iterable[tuple[dict, str, str, str]]) -> IndexStats:
        """records: (meta, ctx_text, title_text, body_text)"""
        t0 = time.time()
        cur = self.conn.cursor()
        cur.execute("DELETE FROM chunk_meta")
        cur.execute("DELETE FROM chunk_fts")
        n_chunks = n_chars = 0
        docs: set[str] = set()
        for meta, ctx, title, body in records:
            cur.execute(
                """INSERT INTO chunk_meta (chunk_uid, doc_id, ord, doc_path, source_type,
                   source_name, published_at, title, filing_type, capture_mode, heading_path,
                   kind, n_chars, raw_text)
                   VALUES (:chunk_uid,:doc_id,:ord,:doc_path,:source_type,:source_name,
                   :published_at,:title,:filing_type,:capture_mode,:heading_path,:kind,
                   :n_chars,:raw_text)""",
                meta,
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
            n_chunks += 1
            n_chars += meta["n_chars"]
            docs.add(meta["doc_id"])
        self.conn.commit()
        self.conn.execute("INSERT INTO chunk_fts(chunk_fts) VALUES('optimize')")
        self.conn.commit()
        return IndexStats(
            n_docs=len(docs),
            n_chunks=n_chunks,
            n_chars_indexed=n_chars,
            build_seconds=round(time.time() - t0, 2),
            db_bytes=self.db_path.stat().st_size,
        )

    # --- Retrieve ----------------------------------------------------------
    def search(
        self,
        query: str,
        k: int = 10,
        *,
        source_types: Sequence[str] | None = None,
        published_after: str | None = None,
        exclude_metadata_only: bool = False,
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
        wide = self.search(query, k=pool, exclude_metadata_only=exclude_metadata_only)
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
                                          best.text, best.capture_mode)))
        scored.sort(key=lambda x: x[0])
        return [h for _, h in scored[:k]]

    def close(self) -> None:
        self.conn.close()

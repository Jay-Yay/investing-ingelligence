"""벡터를 저장하고 뜻으로 찾는 인덱스.

BM25 인덱스와 같은 `chunk_uid`를 키로 쓴다. 같은 조각을 두 방식으로 색인해 두는
것이므로, 나중에 두 결과를 합칠 때 이름만 맞춰 보면 된다.

저장은 SQLite(메타데이터) + .npy(벡터 행렬) 두 파일로 나눴다. 벡터를 SQLite에
BLOB으로 넣어도 되지만, 검색할 때마다 전부 꺼내 배열로 되돌리는 비용이 붙는다.
행렬로 따로 두면 mmap으로 붙여 두고 행렬 곱 한 번으로 끝난다.

전용 벡터 DB를 안 쓴 이유는 조각이 5만 개 규모라서다. float32 1024차원 기준
약 200MB이고, 이 정도면 메모리에 통째로 올려놓고 곱하는 편이 더 빠르고 단순하다.
100만 개를 넘어가면 그때 FAISS 같은 것을 검토하면 된다.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from investor_intel.indexing.embedding import Encoder

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vec_meta (
    row_id      INTEGER PRIMARY KEY,
    chunk_uid   TEXT NOT NULL UNIQUE,
    doc_id      TEXT NOT NULL,
    ord         INTEGER NOT NULL,
    title       TEXT,
    source_type TEXT,
    okf_type    TEXT,
    entity_key  TEXT,
    period_year TEXT,
    pub_year    TEXT,
    okf_status  TEXT,
    heading     TEXT,
    n_chars     INTEGER,
    raw_text    TEXT
);
CREATE INDEX IF NOT EXISTS idx_vec_doc ON vec_meta(doc_id);
CREATE INDEX IF NOT EXISTS idx_vec_entity ON vec_meta(entity_key);
CREATE INDEX IF NOT EXISTS idx_vec_period ON vec_meta(period_year);
CREATE TABLE IF NOT EXISTS vec_info (key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass
class VectorHit:
    chunk_uid: str
    doc_id: str
    score: float
    title: str
    heading: str
    text: str
    source_type: str = ""
    okf_status: str = ""
    entity_key: str = ""
    period_year: str = ""


@dataclass
class VectorBuildStats:
    chunks_embedded: int = 0
    chunks_skipped: int = 0
    docs_embedded: int = 0
    docs_skipped: int = 0
    skipped_by_status: dict[str, int] = None
    dim: int = 0
    model: str = ""
    bytes_on_disk: int = 0

    def __post_init__(self) -> None:
        if self.skipped_by_status is None:
            self.skipped_by_status = {}


class VectorIndex:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.npy_path = self.db_path.with_suffix(".vecs.npy")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self._mat: np.ndarray | None = None

    # ------------------------------------------------------------------ build

    def build(
        self,
        records: Iterable[dict],
        encoder: Encoder,
        *,
        batch_size: int = 256,
        embed_text_key: str = "embed_text",
    ) -> VectorBuildStats:
        """조각을 받아 벡터로 만들어 저장한다.

        `records`의 각 항목은 벡터로 만들 문장(`embed_text`)과 메타데이터를 담는다.
        벡터로 만들 문장에는 조각 본문 앞에 문맥(concept의 description)을 붙여 둔다.
        조각만 떼어놓으면 어느 회사 이야기인지 모르는 경우가 많아서, 문맥이 붙어 있어야
        벡터가 제자리를 찾는다. 3주차의 Contextual Retrieval이 말하는 그 자리다.
        """
        self.conn.execute("DELETE FROM vec_meta")
        stats = VectorBuildStats(model=getattr(encoder, "name", "?"), dim=getattr(encoder, "dim", 0))
        mats: list[np.ndarray] = []
        buf_texts: list[str] = []
        buf_meta: list[dict] = []
        docs: set[str] = set()
        row_id = 0

        def flush():
            nonlocal row_id
            if not buf_texts:
                return
            vecs = encoder.encode_passages(buf_texts)
            mats.append(vecs)
            rows = []
            for meta in buf_meta:
                rows.append((
                    row_id, meta["chunk_uid"], meta["doc_id"], meta.get("ord", 0),
                    meta.get("title", ""), meta.get("source_type", ""),
                    meta.get("okf_type", ""), meta.get("entity_key", ""),
                    meta.get("period_year", ""), meta.get("pub_year", ""),
                    meta.get("okf_status", ""), meta.get("heading", ""),
                    meta.get("n_chars", 0), meta.get("raw_text", ""),
                ))
                row_id += 1
            self.conn.executemany(
                "INSERT INTO vec_meta VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            buf_texts.clear()
            buf_meta.clear()

        for rec in records:
            text = (rec.get(embed_text_key) or "").strip()
            if not text:
                stats.chunks_skipped += 1
                continue
            buf_texts.append(text)
            buf_meta.append(rec)
            docs.add(rec["doc_id"])
            stats.chunks_embedded += 1
            if len(buf_texts) >= batch_size:
                flush()
        flush()
        self.conn.commit()

        mat = np.concatenate(mats) if mats else np.zeros((0, stats.dim), dtype=np.float32)
        np.save(self.npy_path, mat)
        self._mat = mat
        stats.docs_embedded = len(docs)
        stats.dim = int(mat.shape[1]) if mat.size else stats.dim
        stats.bytes_on_disk = self.npy_path.stat().st_size if self.npy_path.exists() else 0
        self.conn.execute(
            "INSERT OR REPLACE INTO vec_info VALUES ('build', ?)",
            (json.dumps({"model": stats.model, "dim": stats.dim,
                         "chunks": stats.chunks_embedded}, ensure_ascii=False),))
        self.conn.commit()
        return stats

    # ----------------------------------------------------------------- search

    @property
    def matrix(self) -> np.ndarray:
        if self._mat is None:
            self._mat = np.load(self.npy_path, mmap_mode="r") if self.npy_path.exists() \
                else np.zeros((0, 0), dtype=np.float32)
        return self._mat

    def _candidate_rows(
        self,
        *,
        entity_key: str | None,
        period_year: str | None,
        okf_types: Sequence[str] | None,
        exclude_status: Sequence[str] | None,
    ) -> np.ndarray | None:
        """메타데이터 조건에 맞는 행 번호만 추린다.

        조건이 하나도 없으면 None을 돌려주고, 그러면 전체 행렬을 그대로 쓴다.
        BM25 쪽과 완전히 같은 조건을 걸어야 두 결과를 합쳤을 때 앞뒤가 맞는다.
        """
        where, params = [], []
        if entity_key:
            where.append("(entity_key = ? OR entity_key LIKE ?)")
            params += [entity_key, f"%|{entity_key}|%"]
        if period_year:
            where.append("(period_year = ? OR pub_year = ?)")
            params += [period_year, period_year]
        if okf_types:
            where.append("okf_type IN (%s)" % ",".join("?" * len(okf_types)))
            params += list(okf_types)
        if exclude_status:
            where.append("okf_status NOT IN (%s)" % ",".join("?" * len(exclude_status)))
            params += list(exclude_status)
        if not where:
            return None
        rows = self.conn.execute(
            f"SELECT row_id FROM vec_meta WHERE {' AND '.join(where)}", params).fetchall()
        return np.fromiter((r["row_id"] for r in rows), dtype=np.int64, count=len(rows))

    def search(
        self,
        query: str,
        encoder: Encoder,
        k: int = 10,
        *,
        entity_key: str | None = None,
        period_year: str | None = None,
        okf_types: Sequence[str] | None = None,
        exclude_status: Sequence[str] | None = None,
    ) -> list[VectorHit]:
        mat = self.matrix
        if mat.size == 0:
            return []
        qv = encoder.encode_queries([query])
        if qv.shape[0] == 0:
            return []
        rows = self._candidate_rows(entity_key=entity_key, period_year=period_year,
                                    okf_types=okf_types, exclude_status=exclude_status)
        if rows is not None:
            if rows.size == 0:
                return []
            sub = np.asarray(mat[rows])
            scores = sub @ qv[0]
            order = np.argsort(-scores)[:k]
            picked = [(int(rows[i]), float(scores[i])) for i in order]
        else:
            scores = np.asarray(mat) @ qv[0]
            order = np.argsort(-scores)[:k]
            picked = [(int(i), float(scores[i])) for i in order]

        by_row = {r: s for r, s in picked}
        q = ",".join("?" * len(by_row))
        got = self.conn.execute(
            f"SELECT * FROM vec_meta WHERE row_id IN ({q})", list(by_row)).fetchall()
        hits = [
            VectorHit(chunk_uid=r["chunk_uid"], doc_id=r["doc_id"], score=by_row[r["row_id"]],
                      title=r["title"] or "", heading=r["heading"] or "",
                      text=r["raw_text"] or "", source_type=r["source_type"] or "",
                      okf_status=r["okf_status"] or "", entity_key=r["entity_key"] or "",
                      period_year=r["period_year"] or "")
            for r in got
        ]
        hits.sort(key=lambda h: -h.score)
        return hits

    def search_documents(self, query: str, encoder: Encoder, k: int = 10, *,
                         pool: int = 300, **filters) -> list[VectorHit]:
        """문서 단위로 접어서 돌려준다.

        한 문서에서 나온 조각 여러 개가 상위를 다 차지하면 후보 다양성이 죽는다.
        BM25 쪽에서 같은 이유로 문서당 상위 1개만 남기는 방식을 썼고, 여기서도
        똑같이 맞춘다. 두 결과를 순위로 합칠 것이므로 단위가 같아야 한다.
        """
        hits = self.search(query, encoder, k=pool, **filters)
        best: dict[str, VectorHit] = {}
        for h in hits:
            if h.doc_id not in best:
                best[h.doc_id] = h
        return sorted(best.values(), key=lambda h: -h.score)[:k]

    def covered_docs(self) -> set[str]:
        return {r["doc_id"] for r in self.conn.execute("SELECT DISTINCT doc_id FROM vec_meta")}

    def close(self) -> None:
        self.conn.close()

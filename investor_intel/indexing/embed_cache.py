"""임베딩을 조각 본문 해시로 캐싱한다.

## 왜 필요한가

`build_vector_index`는 매번 전량 재계산이다. 문서 한 건이 늘어도 조각 4만여 개를 다시
인코딩한다. 임베딩은 이 파이프라인에서 가장 비싼 단계이고(로컬 모델이면 시간, API면 돈),
그래서 "가끔 손으로 돌리는 것"이 될 수밖에 없었다.

조각 본문이 같으면 벡터도 같다. 그러면 다시 계산할 이유가 없다.

## 무엇을 키로 삼는가

`(임베딩할 문장의 해시, 모델 이름)`이다. 문서 id나 chunk_uid가 아닌 이유는, 청크 경계가
밀리는 경우(본문이 조금 길어지면 뒤쪽 청크가 전부 다른 uid를 받는다)에도 **내용이 같은
조각은 그대로 재사용**되어야 하기 때문이다. 문서 하나에 한 문장을 덧붙였을 때 그 문서의
모든 청크를 다시 인코딩하지 않는다.

모델 이름을 키에 넣는 것은, 모델을 바꾸면 벡터 공간 자체가 달라져 섞어 쓸 수 없기 때문이다.

## 저장 형식

float32 배열을 그대로 BLOB으로 넣는다. 차원을 함께 저장해 두고 읽을 때 검증한다 -
같은 모델 이름으로 차원이 다른 벡터가 섞이면 행렬 곱에서 조용히 깨지는 대신 여기서 걸린다.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from investor_intel.indexing.embedding import Encoder

_SCHEMA = """
CREATE TABLE IF NOT EXISTS embedding_cache (
    text_hash TEXT NOT NULL,
    model     TEXT NOT NULL,
    dim       INTEGER NOT NULL,
    vector    BLOB NOT NULL,
    PRIMARY KEY (text_hash, model)
);
"""


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    stored: int = 0

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_ratio(self) -> float:
        return round(self.hits / self.lookups, 4) if self.lookups else 0.0


class EmbeddingCache:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(_SCHEMA)
        self.stats = CacheStats()

    def get_many(self, texts: Sequence[str], model: str, dim: int) -> dict[str, np.ndarray]:
        """캐시에 있는 것만 돌려준다. 없는 것은 키가 아예 없다."""
        out: dict[str, np.ndarray] = {}
        hashes = [text_hash(t) for t in texts]
        for i in range(0, len(hashes), 500):
            batch = hashes[i : i + 500]
            placeholders = ",".join("?" * len(batch))
            rows = self.conn.execute(
                f"SELECT text_hash, dim, vector FROM embedding_cache "
                f"WHERE model = ? AND text_hash IN ({placeholders})",
                [model, *batch],
            ).fetchall()
            for h, stored_dim, blob in rows:
                if stored_dim != dim:
                    # 같은 모델 이름으로 차원이 다른 벡터가 섞였다. 재사용하면 행렬 곱에서
                    # 조용히 깨지므로 캐시 미스로 취급한다.
                    continue
                out[str(h)] = np.frombuffer(blob, dtype=np.float32)
        return out

    def put_many(self, texts: Sequence[str], vectors: np.ndarray, model: str) -> None:
        rows = [
            (text_hash(text), model, int(vectors.shape[1]),
             np.ascontiguousarray(vectors[i], dtype=np.float32).tobytes())
            for i, text in enumerate(texts)
        ]
        self.conn.executemany(
            "INSERT OR REPLACE INTO embedding_cache (text_hash, model, dim, vector) "
            "VALUES (?,?,?,?)",
            rows,
        )
        self.conn.commit()
        self.stats.stored += len(rows)

    def size(self, model: str | None = None) -> int:
        if model is None:
            return int(self.conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0])
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM embedding_cache WHERE model = ?", (model,)
            ).fetchone()[0]
        )

    def close(self) -> None:
        self.conn.close()


class CachedEncoder:
    """`Encoder` 프로토콜을 만족하면서, 문서 인코딩만 캐시를 거친다.

    질의(`encode_queries`)는 캐시하지 않는다. 매번 다른 문장이고 한 번에 하나라서 캐시
    적중률이 사실상 0이면서 캐시만 부풀린다.
    """

    def __init__(self, inner: Encoder, cache: EmbeddingCache) -> None:
        self._inner = inner
        self._cache = cache
        self.name = getattr(inner, "name", "?")
        self.dim = getattr(inner, "dim", 0)

    @property
    def stats(self) -> CacheStats:
        return self._cache.stats

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        cached = self._cache.get_many(texts, self.name, self.dim)
        hashes = [text_hash(t) for t in texts]
        missing_idx = [i for i, h in enumerate(hashes) if h not in cached]
        self._cache.stats.hits += len(texts) - len(missing_idx)
        self._cache.stats.misses += len(missing_idx)

        if missing_idx:
            missing_texts = [texts[i] for i in missing_idx]
            fresh = self._inner.encode_passages(missing_texts)
            self._cache.put_many(missing_texts, fresh, self.name)
            for slot, i in enumerate(missing_idx):
                cached[hashes[i]] = fresh[slot]

        # 같은 문장이 두 번 들어와도(중복 청크) 순서대로 그대로 채운다.
        return np.stack([cached[h] for h in hashes]).astype(np.float32)

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._inner.encode_queries(texts)

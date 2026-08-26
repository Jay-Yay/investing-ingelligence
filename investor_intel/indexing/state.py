"""무엇이 색인됐는지를 기록해, 바뀐 것만 다시 색인할 수 있게 한다.

## 왜 필요한가

`Bm25Index.build()`는 `DELETE FROM chunk_meta`로 시작한다. 문서 한 건이 늘어도 4,818건을
전부 다시 청킹·토크나이징·색인한다. 수집은 증분인데 색인은 전량이라 둘의 주기가 맞지 않고,
결국 색인은 "가끔 손으로 돌리는 것"이 된다 - 실제로 한 달 가까이 밀려 있었고, 그 사실을
관측할 지표조차 없었다.

## 무엇을 키로 삼는가

concept 파일의 **원문 바이트 해시**다. 처음에는 원본 문서의 `content_hash`를 쓰려 했지만
그것으로는 부족하다. 색인되는 것은 본문만이 아니라 `description`(청크 문맥), `entities`
(필터 컬럼), `status`까지다. `enrich-vault`로 종목 관계가 붙으면 본문 `content_hash`는
그대로인데 색인 내용은 달라진다 - 그 경우를 놓치면 필터가 조용히 옛 값으로 남는다.

concept 파일 전체를 해시하면 그 모든 경우가 한 번에 잡힌다. 파일은 어차피 읽어야 하므로
추가 비용도 없다.

## 코드가 바뀌면

청킹 규칙이나 토크나이저가 바뀌면 파일 해시는 그대로인데 색인 결과는 달라져야 한다.
그래서 인덱스 단위로 `signature`(변형 이름 + 빌더 버전)를 저장하고, 이것이 달라지면
증분이 아니라 전량 재구축으로 떨어진다. 조용히 옛 색인을 유지하는 것보다 안전하다.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime

# 청킹·토크나이징·문맥 조립 규칙이 바뀔 때 손으로 올린다. 올리면 다음 `index update`가
# 전량 재구축을 한다. 다만 chunk_fts의 content 모드(contentless 여부)처럼 CREATE VIRTUAL
# TABLE 자체를 바꾸는 스키마 변경은 `index build`가 하는 DELETE FROM으로는 반영되지 않는다
# (테이블 구조는 그대로 두고 행만 지우기 때문) - `data/search_index.sqlite3` 파일 자체를
# 지우고 다시 만들어야 한다.
BUILDER_VERSION = "2026-08-26.2"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS index_state (
    doc_id       TEXT PRIMARY KEY,
    fingerprint  TEXT NOT NULL,
    chunk_count  INTEGER NOT NULL DEFAULT 0,
    indexed_at   TEXT NOT NULL,
    embedded_at  TEXT,
    embed_model  TEXT
);
CREATE TABLE IF NOT EXISTS index_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def fingerprint(raw: str, signature: str) -> str:
    """concept 파일 내용과 인덱스 설정을 합친 지문."""
    digest = hashlib.sha256(f"{signature}\x00{raw}".encode())
    return digest.hexdigest()[:32]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class UpdatePlan:
    """무엇을 다시 색인해야 하는가."""

    changed: dict[str, str] = field(default_factory=dict)   # doc_id -> fingerprint
    unchanged: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    full_rebuild: bool = False
    rebuild_reason: str = ""

    @property
    def is_noop(self) -> bool:
        return not self.full_rebuild and not self.changed and not self.removed


class IndexState:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.executescript(_SCHEMA)

    # --- 인덱스 단위 메타 -------------------------------------------------
    def get_info(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM index_info WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set_info(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO index_info (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # --- 문서 단위 상태 ---------------------------------------------------
    def fingerprints(self) -> dict[str, str]:
        return {
            str(row[0]): str(row[1])
            for row in self.conn.execute("SELECT doc_id, fingerprint FROM index_state")
        }

    def record_indexed(self, doc_id: str, fp: str, chunk_count: int) -> None:
        self.conn.execute(
            "INSERT INTO index_state (doc_id, fingerprint, chunk_count, indexed_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(doc_id) DO UPDATE SET "
            "fingerprint = excluded.fingerprint, chunk_count = excluded.chunk_count, "
            # 내용이 바뀌어 다시 색인했으면 임베딩도 낡았다. 지워야 다음 벡터 갱신이 집는다.
            "indexed_at = excluded.indexed_at, embedded_at = NULL, embed_model = NULL",
            (doc_id, fp, chunk_count, now_iso()),
        )

    def record_embedded(self, doc_id: str, model: str) -> None:
        self.conn.execute(
            "UPDATE index_state SET embedded_at = ?, embed_model = ? WHERE doc_id = ?",
            (now_iso(), model, doc_id),
        )

    def forget(self, doc_ids: set[str]) -> None:
        self.conn.executemany(
            "DELETE FROM index_state WHERE doc_id = ?", [(doc_id,) for doc_id in doc_ids]
        )

    def clear(self) -> None:
        self.conn.execute("DELETE FROM index_state")

    def docs_needing_embedding(self, model: str) -> set[str]:
        """색인은 됐지만 이 모델로 임베딩되지 않은 문서."""
        return {
            str(row[0])
            for row in self.conn.execute(
                "SELECT doc_id FROM index_state "
                "WHERE embedded_at IS NULL OR embed_model IS NOT ?",
                (model,),
            )
        }

    # --- 계획 ------------------------------------------------------------
    def plan(self, present: dict[str, str], signature: str) -> UpdatePlan:
        """현재 번들의 지문과 기록을 비교해 무엇을 다시 색인할지 정한다."""
        stored_signature = self.get_info("signature")
        if stored_signature is None:
            return UpdatePlan(changed=dict(present), full_rebuild=True,
                              rebuild_reason="인덱스 상태 기록이 없음 (첫 빌드)")
        if stored_signature != signature:
            return UpdatePlan(
                changed=dict(present), full_rebuild=True,
                rebuild_reason=f"인덱스 설정 변경 ({stored_signature} -> {signature})")

        known = self.fingerprints()
        changed = {doc_id: fp for doc_id, fp in present.items() if known.get(doc_id) != fp}
        return UpdatePlan(
            changed=changed,
            unchanged={doc_id for doc_id in present if doc_id not in changed},
            removed=set(known) - set(present),
        )

    def summary(self) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*) AS docs, COALESCE(SUM(chunk_count), 0) AS chunks, "
            "SUM(embedded_at IS NOT NULL) AS embedded, MIN(indexed_at) AS oldest, "
            "MAX(indexed_at) AS newest FROM index_state"
        ).fetchone()
        return {
            "docs": row["docs"], "chunks": row["chunks"],
            "embedded": row["embedded"] or 0,
            "oldest_indexed_at": row["oldest"], "newest_indexed_at": row["newest"],
            "signature": self.get_info("signature"),
        }

"""수집·색인 파이프라인의 건강 지표.

## 왜 필요한가

색인이 한 달 가까이 밀려 있었는데 그 사실을 관측할 방법이 없었다. "수집된 문서 4,818건"과
"색인된 청크 47,121개"는 각각 알 수 있었지만, **둘이 맞는지**를 물어볼 수 있는 곳이 없었다.

여기서 답하는 질문은 셋이다.

1. 수집은 됐는데 색인 안 된 문서가 몇 건인가 (색인이 밀렸는가)
2. 근거로 쓸 수 없는 문서가 몇 건인가 (본문 미확보·인코딩 손상·절단)
3. 그 비율이 나빠지고 있는가 (CI에서 막아야 하는가)

## 게이트로 쓸 때

`Thresholds`가 실패 조건을 담는다. 기본값은 "지금보다 나빠지면 실패"가 아니라 "절대
기준"이다 - 상대 기준은 기준선 파일을 따로 관리해야 하고, 그 파일이 낡으면 게이트가
조용히 무력화된다. 대신 임계값을 명시적으로 넘겨 프로젝트 상태에 맞출 수 있게 했다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from investor_intel.indexing.bm25_index import Bm25Index
from investor_intel.indexing.state import IndexState
from investor_intel.ingest.quality import CORRUPT_RATIO_THRESHOLD


@dataclass
class SourceHealth:
    source_type: str
    documents: int = 0
    stub: int = 0
    corrupt: int = 0
    truncated: int = 0

    @property
    def unusable(self) -> int:
        """근거로 인용할 수 없는 문서. 세 이유는 겹칠 수 있어 상한이 아니라 합집합 근사다."""
        return self.stub + self.corrupt

    @property
    def stub_ratio(self) -> float:
        return round(self.stub / self.documents, 4) if self.documents else 0.0

    @property
    def corrupt_ratio(self) -> float:
        return round(self.corrupt / self.documents, 4) if self.documents else 0.0


@dataclass
class IndexHealth:
    by_source: list[SourceHealth] = field(default_factory=list)
    documents: int = 0
    stub: int = 0
    corrupt: int = 0
    truncated: int = 0
    # 카탈로그에 있는데 색인에 없는 문서. 색인이 밀린 정도다.
    not_indexed: int = 0
    indexed_docs: int = 0
    indexed_chunks: int = 0
    embedded_docs: int = 0
    signature: str | None = None
    newest_indexed_at: str | None = None
    newest_collected_at: str | None = None
    index_present: bool = False
    legacy_unit_snapshots: int | None = None

    @property
    def corrupt_ratio(self) -> float:
        return round(self.corrupt / self.documents, 4) if self.documents else 0.0

    @property
    def stub_ratio(self) -> float:
        return round(self.stub / self.documents, 4) if self.documents else 0.0

    @property
    def index_lag(self) -> int:
        return self.not_indexed


@dataclass
class Thresholds:
    """CI 게이트가 실패로 볼 조건."""

    max_corrupt: int = 0
    max_not_indexed: int | None = None
    max_stub_ratio: float | None = None

    def failures(self, health: IndexHealth) -> list[str]:
        out: list[str] = []
        if health.corrupt > self.max_corrupt:
            out.append(
                f"인코딩 손상 문서 {health.corrupt}건 (허용 {self.max_corrupt}건). "
                "재수집이 필요하다 - `refetch --reason corrupt`")
        if self.max_not_indexed is not None and health.not_indexed > self.max_not_indexed:
            out.append(
                f"색인 안 된 문서 {health.not_indexed}건 (허용 {self.max_not_indexed}건). "
                "`index update`를 실행하라")
        if self.max_stub_ratio is not None and health.stub_ratio > self.max_stub_ratio:
            out.append(
                f"본문 미확보 비율 {health.stub_ratio:.1%} (허용 {self.max_stub_ratio:.1%}). "
                "`refetch --reason stub`")
        return out


def _catalog_health(conn: sqlite3.Connection) -> tuple[list[SourceHealth], str | None]:
    rows = conn.execute(
        "SELECT source_type, COUNT(*) AS documents, "
        "SUM(capture_mode != 'full') AS stub, "
        "SUM(readable_ratio < ?) AS corrupt, "
        "SUM(truncated) AS truncated "
        "FROM documents GROUP BY source_type ORDER BY source_type",
        (1.0 - CORRUPT_RATIO_THRESHOLD,),
    ).fetchall()
    newest = conn.execute("SELECT MAX(collected_at) FROM documents").fetchone()[0]
    return [
        SourceHealth(
            source_type=str(row["source_type"]), documents=int(row["documents"]),
            stub=int(row["stub"] or 0), corrupt=int(row["corrupt"] or 0),
            truncated=int(row["truncated"] or 0),
        )
        for row in rows
    ], newest


def _legacy_unit_snapshots(structured_db: Path | None) -> int | None:
    if structured_db is None or not structured_db.exists():
        return None
    conn = sqlite3.connect(structured_db)
    try:
        return int(
            conn.execute("SELECT COUNT(*) FROM snapshots WHERE legacy_units = 1").fetchone()[0]
        )
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def collect_health(
    catalog_conn: sqlite3.Connection,
    search_db: Path | None = None,
    structured_db: Path | None = None,
) -> IndexHealth:
    by_source, newest_collected = _catalog_health(catalog_conn)
    health = IndexHealth(
        by_source=by_source,
        documents=sum(s.documents for s in by_source),
        stub=sum(s.stub for s in by_source),
        corrupt=sum(s.corrupt for s in by_source),
        truncated=sum(s.truncated for s in by_source),
        newest_collected_at=newest_collected,
        legacy_unit_snapshots=_legacy_unit_snapshots(structured_db),
    )

    if search_db is None or not Path(search_db).exists():
        # 인덱스가 아예 없으면 카탈로그 전체가 미색인이다.
        health.not_indexed = health.documents
        return health

    index = Bm25Index(Path(search_db))
    try:
        health.index_present = True
        stats = index.stats()
        health.indexed_docs = stats.n_docs
        health.indexed_chunks = stats.n_chunks
        state = IndexState(index.conn)
        summary = state.summary()
        health.embedded_docs = int(summary["embedded"] or 0)
        health.signature = summary["signature"]
        health.newest_indexed_at = summary["newest_indexed_at"]

        indexed_native = index.indexed_native_ids()
        catalog_ids = {
            str(row[0]) for row in catalog_conn.execute("SELECT id FROM documents")
        }
        health.not_indexed = len(catalog_ids - indexed_native) if indexed_native else 0
        if not indexed_native:
            # native_doc_id를 쓰기 전에 만든 인덱스. 정확히 셀 수 없으므로 문서 수 차이로
            # 근사하고, 음수는 0으로 둔다(색인 쪽에 허브 concept이 더 있을 수 있다).
            health.not_indexed = max(0, health.documents - health.indexed_docs)
    finally:
        index.close()
    return health

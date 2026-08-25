from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from investor_intel.indexing.config import V7
from investor_intel.indexing.health import IndexHealth, Thresholds, collect_health
from investor_intel.indexing.okf_pipeline import build_okf_index
from investor_intel.knowledge.schema import Concept, Period, Provenance
from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import ContentCapture, SourceDocument
from investor_intel.storage.sqlite_index import connect, init_db, upsert_document


def _doc(doc_id: str, *, source_type: SourceType = SourceType.DART, capture: str = "full",
         readable: float = 1.0, truncated: bool = False) -> SourceDocument:
    return SourceDocument(
        id=doc_id, source_type=source_type, source_name="000660", author="a",
        title="t", source_url=f"https://example.com/{doc_id}", source_specific_id=doc_id,
        published_at=datetime(2026, 7, 1, tzinfo=UTC),
        collected_at=datetime(2026, 7, 2, tzinfo=UTC),
        language="ko", content_hash=f"h-{doc_id}",
        content_capture=ContentCapture(
            mode=ContentCaptureMode(capture),
            reason=None if capture == "full" else "본문 미확보",
        ),
        document_type="dart_filing", readable_ratio=readable, truncated=truncated,
    )


def _catalog(tmp_path: Path, docs):
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    for doc in docs:
        upsert_document(conn, doc, file_path=f"10_Sources/{doc.id}.md")
    return conn


def test_health_counts_unusable_documents_per_source(tmp_path: Path) -> None:
    conn = _catalog(tmp_path, [
        _doc("a"),
        _doc("b", capture="metadata_only"),
        _doc("c", readable=0.5),
        _doc("d", truncated=True),
        _doc("e", source_type=SourceType.TELEGRAM),
    ])
    health = collect_health(conn)
    conn.close()

    assert health.documents == 5
    assert health.stub == 1
    assert health.corrupt == 1
    assert health.truncated == 1
    by_type = {s.source_type: s for s in health.by_source}
    assert by_type["dart"].documents == 4
    assert by_type["telegram"].corrupt == 0


def test_missing_index_reports_everything_as_not_indexed(tmp_path: Path) -> None:
    """인덱스가 아예 없으면 "0건 밀렸다"가 아니라 "전부 밀렸다"가 맞다."""
    conn = _catalog(tmp_path, [_doc("a"), _doc("b")])
    health = collect_health(conn, search_db=tmp_path / "absent.sqlite3")
    conn.close()
    assert not health.index_present
    assert health.not_indexed == 2


def test_health_joins_the_index_back_to_the_catalog(tmp_path: Path) -> None:
    """색인이 밀린 정도를 정확히 세려면 concept이 아니라 원본 문서 id로 맞춰야 한다."""
    bundle = tmp_path / "20_Knowledge"
    path = bundle / "commentary" / "c-a.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        Concept(
            type="MarketCommentary", title="t", description="d", key="c-a",
            folder="commentary", period=Period(published="2026-07-01"),
            provenance=Provenance(system="dart", native_id="", collected_at="",
                                  content_hash="a", source_path=""),
            body="본문",
        ).render(),
        encoding="utf-8",
    )
    search_db = tmp_path / "search.sqlite3"
    build_okf_index(bundle, search_db, V7)[0].close()

    conn = _catalog(tmp_path, [_doc("a"), _doc("b")])
    health = collect_health(conn, search_db=search_db)
    conn.close()

    assert health.index_present
    assert health.signature.startswith("V7/")
    assert health.not_indexed == 1          # b는 번들에 없다


def test_gate_fails_on_corrupt_documents() -> None:
    health = IndexHealth(documents=100, corrupt=3)
    failures = Thresholds(max_corrupt=0).failures(health)
    assert len(failures) == 1
    assert "refetch" in failures[0]


def test_gate_passes_when_within_the_allowance() -> None:
    health = IndexHealth(documents=100, corrupt=3)
    assert Thresholds(max_corrupt=5).failures(health) == []


def test_gate_can_watch_index_lag() -> None:
    health = IndexHealth(documents=100, not_indexed=40)
    failures = Thresholds(max_corrupt=10, max_not_indexed=0).failures(health)
    assert len(failures) == 1
    assert "index update" in failures[0]


def test_gate_can_watch_the_stub_ratio() -> None:
    health = IndexHealth(documents=100, stub=40)
    failures = Thresholds(max_corrupt=0, max_stub_ratio=0.3).failures(health)
    assert len(failures) == 1
    assert "40.0%" in failures[0]


def test_thresholds_that_are_not_set_are_not_checked() -> None:
    """임계값을 안 주면 검사도 하지 않는다 - status를 그냥 조회용으로 쓸 수 있어야 한다."""
    health = IndexHealth(documents=100, stub=99, not_indexed=99)
    assert Thresholds(max_corrupt=10**9).failures(health) == []

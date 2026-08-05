from datetime import UTC, datetime, timedelta

from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import ContentCapture, SourceDocument
from investor_intel.pipeline.stock_score import find_recent_documents_for_ticker
from investor_intel.storage.obsidian_repo import write_document
from investor_intel.storage.sqlite_index import connect, init_db, reindex


def _doc(
    doc_id: str,
    companies: list[str],
    published_at: datetime,
    source_type: SourceType = SourceType.IB_INSIGHTS,
) -> SourceDocument:
    return SourceDocument(
        id=doc_id,
        source_type=source_type,
        source_name="교보증권",
        title="테스트 리포트",
        source_url=f"https://example.com/{doc_id}",
        published_at=published_at,
        collected_at=published_at,
        language="ko",
        content_hash=f"hash-{doc_id}",
        content_capture=ContentCapture(mode=ContentCaptureMode.FULL),
        companies=companies,
        document_type="ib_research_summary",
    )


def _setup(tmp_path):
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    return vault_path, conn


def test_finds_document_matching_companies_field_via_dart_code(tmp_path) -> None:
    # 문서 프론트매터의 companies는 거래소 접미사 없는 6자리 코드("005930")를 쓴다 - universe.yaml
    # 표기("005930.KS")와 다르므로 이 매칭이 핵심 회귀 지점이다.
    vault_path, conn = _setup(tmp_path)
    now = datetime.now(UTC)
    doc = _doc("d1", ["005930"], now - timedelta(days=1))
    write_document(vault_path, doc, "## 원문\n\n본문")
    reindex(conn, vault_path)

    results = find_recent_documents_for_ticker(conn, vault_path, "005930.KS", since_days=14)
    assert len(results) == 1
    assert results[0][0] == "교보증권"


def test_excludes_documents_mentioning_a_different_company(tmp_path) -> None:
    vault_path, conn = _setup(tmp_path)
    now = datetime.now(UTC)
    doc = _doc("d1", ["000660"], now - timedelta(days=1))  # SK하이닉스, 아닌 종목
    write_document(vault_path, doc, "## 원문\n\n본문")
    reindex(conn, vault_path)

    results = find_recent_documents_for_ticker(conn, vault_path, "005930.KS", since_days=14)
    assert results == []


def test_excludes_documents_outside_the_lookback_window(tmp_path) -> None:
    vault_path, conn = _setup(tmp_path)
    now = datetime.now(UTC)
    old_doc = _doc("d1", ["005930"], now - timedelta(days=30))
    write_document(vault_path, old_doc, "## 원문\n\n본문")
    reindex(conn, vault_path)

    results = find_recent_documents_for_ticker(conn, vault_path, "005930.KS", since_days=14)
    assert results == []


def test_matches_multiple_companies_in_one_document(tmp_path) -> None:
    vault_path, conn = _setup(tmp_path)
    now = datetime.now(UTC)
    doc = _doc("d1", ["005930", "000660"], now - timedelta(days=1))
    write_document(vault_path, doc, "## 원문\n\n삼성전자와 SK하이닉스 비교 리포트")
    reindex(conn, vault_path)

    assert len(find_recent_documents_for_ticker(conn, vault_path, "005930.KS", since_days=14)) == 1
    assert len(find_recent_documents_for_ticker(conn, vault_path, "000660.KS", since_days=14)) == 1

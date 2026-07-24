from datetime import UTC, datetime
from types import SimpleNamespace

from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import ContentCapture, SourceDocument
from investor_intel.pipeline.analyze import (
    analyze_pending_documents,
    find_unprocessed_document_paths,
)
from investor_intel.storage.content_hash import compute_content_hash
from investor_intel.storage.cost_ledger import init_cost_ledger
from investor_intel.storage.obsidian_repo import read_document, write_document
from investor_intel.storage.sqlite_index import connect, init_db, upsert_document

_BODY_WITH_SECTIONS = (
    "## 원문\n\n본문 내용\n\n"
    "## 블로그 수집 시 유의사항\n\n- 유의사항\n\n"
    "## 핵심 주장\n\n"
    "## 근거\n\n"
    "## 반대 근거\n\n"
    "## 언급 자산\n\n"
    "## 포트폴리오 관련성\n\n"
    "## 출처\n\n- [원문](https://example.com)\n"
)

_VALID_CLAIMS_INPUT = {
    "claims": [
        {
            "claim": "엔비디아 실적이 예상을 상회했다",
            "evidence": ["매출 YoY 30% 증가"],
            "counter_evidence": [],
            "assets": [],
            "fact_or_opinion": "fact",
            "direction": "bullish",
            "confidence": "high",
        }
    ]
}


def _doc(doc_id: str) -> SourceDocument:
    return SourceDocument(
        id=doc_id,
        source_type=SourceType.NAVER,
        source_name="engineerinvestor",
        author="engineerinvestor",
        title="테스트 문서",
        source_url=f"https://example.com/{doc_id}",
        source_specific_id=doc_id,
        published_at=datetime(2026, 7, 24, tzinfo=UTC),
        collected_at=datetime(2026, 7, 24, tzinfo=UTC),
        language="ko",
        content_hash="hash-" + doc_id,
        content_capture=ContentCapture(mode=ContentCaptureMode.FULL),
        document_type="blog_post",
    )


class _FakeAnthropicClient:
    model = "claude-sonnet-5"

    def __init__(self, response):
        self._response = response

    def create_message(self, **kwargs):
        return self._response


def _tool_use_response() -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=_VALID_CLAIMS_INPUT)])


def _setup(tmp_path):
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    init_cost_ledger(conn)
    return vault_path, conn


def test_find_unprocessed_document_paths_lists_pending_docs(tmp_path) -> None:
    vault_path, conn = _setup(tmp_path)
    doc = _doc("doc-1")
    path = write_document(vault_path, doc, "본문 내용")
    upsert_document(conn, doc, file_path=str(path), source_specific_id=doc.source_specific_id)

    paths = find_unprocessed_document_paths(conn)
    assert paths == [str(path)]


def test_analyze_marks_document_processed_and_records_cost(tmp_path) -> None:
    vault_path, conn = _setup(tmp_path)
    doc = _doc("doc-1")
    path = write_document(vault_path, doc, _BODY_WITH_SECTIONS)
    upsert_document(conn, doc, file_path=str(path), source_specific_id=doc.source_specific_id)

    client = _FakeAnthropicClient(_tool_use_response())
    cost_tracker = CostTracker(conn, daily_budget_usd=10.0, monthly_budget_usd=100.0)

    result = analyze_pending_documents(
        conn, vault_path, client, cost_tracker, system_prompt="시스템 프롬프트"
    )

    assert result.processed == 1
    assert result.errors == []
    assert doc.id in result.extractions

    updated_doc, updated_body = read_document(path)
    assert updated_doc.llm_processed is True
    assert updated_doc.llm_model == "claude-sonnet-5"
    assert find_unprocessed_document_paths(conn) == []
    assert cost_tracker.daily_total_usd() > 0

    # the extracted claim must actually be spliced into the document body, and the
    # stored content_hash must match what's really on disk
    assert "엔비디아 실적이 예상을 상회했다" in updated_body
    assert "매출 YoY 30% 증가" in updated_body
    assert updated_doc.content_hash == compute_content_hash(updated_body)


def test_analyze_stops_when_budget_exhausted(tmp_path) -> None:
    vault_path, conn = _setup(tmp_path)
    doc1 = _doc("doc-1")
    doc2 = _doc("doc-2")
    path1 = write_document(vault_path, doc1, "본문 내용 1")
    path2 = write_document(vault_path, doc2, "본문 내용 2")
    upsert_document(conn, doc1, file_path=str(path1), source_specific_id=doc1.source_specific_id)
    upsert_document(conn, doc2, file_path=str(path2), source_specific_id=doc2.source_specific_id)

    client = _FakeAnthropicClient(_tool_use_response())
    cost_tracker = CostTracker(conn, daily_budget_usd=0.0, monthly_budget_usd=100.0)

    result = analyze_pending_documents(
        conn, vault_path, client, cost_tracker, system_prompt="시스템 프롬프트"
    )

    assert result.processed == 0
    assert len(find_unprocessed_document_paths(conn)) == 2

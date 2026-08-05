from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from investor_intel.llm.cost_tracker import CostTracker, compute_cost_usd
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


def _doc(
    doc_id: str,
    source_type: SourceType = SourceType.NAVER,
    source_name: str = "engineerinvestor",
    published_at: datetime | None = None,
) -> SourceDocument:
    return SourceDocument(
        id=doc_id,
        source_type=source_type,
        source_name=source_name,
        author=source_name,
        title="테스트 문서",
        source_url=f"https://example.com/{doc_id}",
        source_specific_id=doc_id,
        published_at=published_at or datetime.now(UTC),
        collected_at=datetime.now(UTC),
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


_KNOWN_INPUT_TOKENS = 123
_KNOWN_OUTPUT_TOKENS = 45


def _tool_use_response() -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input=_VALID_CLAIMS_INPUT)],
        usage=SimpleNamespace(
            input_tokens=_KNOWN_INPUT_TOKENS, output_tokens=_KNOWN_OUTPUT_TOKENS
        ),
    )


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


def _store(vault_path, conn, doc: SourceDocument) -> str:
    path = write_document(vault_path, doc, "본문 내용")
    upsert_document(conn, doc, file_path=str(path), source_specific_id=doc.source_specific_id)
    return str(path)


def test_old_unrelated_document_excluded_from_backlog(tmp_path) -> None:
    """포트폴리오 종목과 무관하고 최근(recent_days) 밖인 히스토리컬 백필 문서는 제외한다."""
    vault_path, conn = _setup(tmp_path)
    old_doc = _doc(
        "old-1",
        source_type=SourceType.NAVER,
        source_name="engineerinvestor",
        published_at=datetime.now(UTC) - timedelta(days=400),
    )
    _store(vault_path, conn, old_doc)

    assert find_unprocessed_document_paths(conn, portfolio_tickers={"NBIS"}) == []


def test_old_document_included_within_recent_days_regardless_of_ticker(tmp_path) -> None:
    """티커와 무관해도 최근 recent_days 이내 문서는 일반 팔로업 창에 포함된다."""
    vault_path, conn = _setup(tmp_path)
    doc = _doc(
        "recent-1",
        source_type=SourceType.NAVER,
        source_name="engineerinvestor",
        published_at=datetime.now(UTC) - timedelta(days=3),
    )
    path = _store(vault_path, conn, doc)

    assert find_unprocessed_document_paths(conn, portfolio_tickers={"NBIS"}) == [path]


def test_ticker_document_within_followup_window_included_even_if_outside_recent_days(
    tmp_path,
) -> None:
    """보유 종목(DART/SEC/웹서치, source_name=티커) 문서는 6개월 팔로업 창 안이면 포함된다."""
    vault_path, conn = _setup(tmp_path)
    doc = _doc(
        "ticker-1",
        source_type=SourceType.WEB_SEARCH,
        source_name="NBIS",
        published_at=datetime.now(UTC) - timedelta(days=90),
    )
    path = _store(vault_path, conn, doc)

    assert find_unprocessed_document_paths(conn, portfolio_tickers={"NBIS"}) == [path]
    # 그 종목이 보유 목록에 없으면(=티커 팔로업 창 미적용) recent_days 밖이라 제외된다.
    assert find_unprocessed_document_paths(conn, portfolio_tickers={"BE"}) == []


def test_ticker_document_outside_followup_window_excluded(tmp_path) -> None:
    """보유 종목 문서라도 ticker_followup_days(기본 180일)를 넘으면 제외한다."""
    vault_path, conn = _setup(tmp_path)
    doc = _doc(
        "ticker-old-1",
        source_type=SourceType.DART,
        source_name="000660",
        published_at=datetime.now(UTC) - timedelta(days=200),
    )
    _store(vault_path, conn, doc)

    assert find_unprocessed_document_paths(conn, portfolio_tickers={"000660"}) == []


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
    expected_cost = compute_cost_usd(
        client.model, _KNOWN_INPUT_TOKENS, _KNOWN_OUTPUT_TOKENS
    )
    assert cost_tracker.daily_total_usd() == expected_cost

    # the extracted claim must actually be spliced into the document body, and the
    # stored content_hash must match what's really on disk
    assert "엔비디아 실적이 예상을 상회했다" in updated_body
    assert "매출 YoY 30% 증가" in updated_body
    assert updated_doc.content_hash == compute_content_hash(updated_body)


def test_analyze_routes_large_document_to_large_doc_client(tmp_path) -> None:
    """SEC 10-K/10-Q 전문 캡처(글자 제한 제거) 이후 대형 문서가 기본(비싼) 모델로 돌아가면
    문서 1건이 하루 LLM 예산을 통째로 잡아먹을 수 있다 - large_doc_char_threshold를 넘는
    문서는 large_doc_client(보통 더 저렴한 모델)로 라우팅돼야 한다.
    """
    vault_path, conn = _setup(tmp_path)
    large_body = "## 원문\n\n" + ("실적 발표 본문 " * 10_000) + "\n\n## 핵심 주장\n\n"
    doc = _doc("doc-large")
    path = write_document(vault_path, doc, large_body)
    upsert_document(conn, doc, file_path=str(path), source_specific_id=doc.source_specific_id)

    default_client = _FakeAnthropicClient(_tool_use_response())
    default_client.model = "claude-sonnet-5"
    large_doc_client = _FakeAnthropicClient(_tool_use_response())
    large_doc_client.model = "claude-haiku-4-5"
    cost_tracker = CostTracker(conn, daily_budget_usd=10.0, monthly_budget_usd=100.0)

    result = analyze_pending_documents(
        conn,
        vault_path,
        default_client,
        cost_tracker,
        system_prompt="시스템 프롬프트",
        large_doc_client=large_doc_client,
        large_doc_char_threshold=1_000,
    )

    assert result.processed == 1
    updated_doc, _ = read_document(path)
    assert updated_doc.llm_model == "claude-haiku-4-5"


def test_analyze_keeps_small_document_on_default_client(tmp_path) -> None:
    vault_path, conn = _setup(tmp_path)
    doc = _doc("doc-small")
    path = write_document(vault_path, doc, _BODY_WITH_SECTIONS)
    upsert_document(conn, doc, file_path=str(path), source_specific_id=doc.source_specific_id)

    default_client = _FakeAnthropicClient(_tool_use_response())
    default_client.model = "claude-sonnet-5"
    large_doc_client = _FakeAnthropicClient(_tool_use_response())
    large_doc_client.model = "claude-haiku-4-5"
    cost_tracker = CostTracker(conn, daily_budget_usd=10.0, monthly_budget_usd=100.0)

    result = analyze_pending_documents(
        conn,
        vault_path,
        default_client,
        cost_tracker,
        system_prompt="시스템 프롬프트",
        large_doc_client=large_doc_client,
        large_doc_char_threshold=1_000_000,
    )

    assert result.processed == 1
    updated_doc, _ = read_document(path)
    assert updated_doc.llm_model == "claude-sonnet-5"


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


def _metadata_only_doc(doc_id: str) -> SourceDocument:
    doc = _doc(doc_id)
    return doc.model_copy(
        update={
            "content_capture": ContentCapture(
                mode=ContentCaptureMode.METADATA_ONLY, reason="테스트용 metadata_only 문서"
            )
        }
    )


_METADATA_ONLY_BODY = (
    "## 원문\n\n삼성전자 주요사항보고서(자기주식취득결정) — 접수일 2026-01-29\n\n"
    "(본문 미제공 - 원문 링크 참고)\n\n"
    "## 핵심 주장\n\n"
    "## 근거\n\n"
    "## 반대 근거\n\n"
    "## 언급 자산\n\n"
    "## 출처\n\n- [원문](https://example.com)\n"
)


def test_analyze_skips_metadata_only_document_without_calling_llm(tmp_path) -> None:
    """content_capture.mode가 metadata_only인 문서(절차적 공시 등)는 원문 자체가 없으므로
    LLM을 부르지 않고 바로 claims=[]로 처리해야 한다 - 예산이 0이어도 적용된다(비용이
    들지 않으므로)."""
    vault_path, conn = _setup(tmp_path)
    doc = _metadata_only_doc("doc-metadata-only")
    path = write_document(vault_path, doc, _METADATA_ONLY_BODY)
    upsert_document(conn, doc, file_path=str(path), source_specific_id=doc.source_specific_id)

    client = _FakeAnthropicClient(_tool_use_response())
    cost_tracker = CostTracker(conn, daily_budget_usd=0.0, monthly_budget_usd=100.0)

    result = analyze_pending_documents(
        conn, vault_path, client, cost_tracker, system_prompt="시스템 프롬프트"
    )

    assert result.processed == 1
    assert result.errors == []
    updated_doc, updated_body = read_document(path)
    assert updated_doc.llm_processed is True
    assert updated_doc.llm_model == "rule_based_skip"
    assert cost_tracker.daily_total_usd() == 0.0
    assert "(추출된 핵심 주장 없음)" in updated_body


def test_analyze_skips_link_digest_document_without_calling_llm(tmp_path) -> None:
    """실제 기사 본문 없이 인기 리포트 링크만 나열하는 다이제스트 패턴도 LLM 없이 걸러진다."""
    vault_path, conn = _setup(tmp_path)
    doc = _doc("doc-digest")
    body = (
        "## 원문\n\n📈 요즘 많이 보는 리포트 TOP 10\n삼성전자 [링크]\n\n"
        "## 핵심 주장\n\n## 근거\n\n## 반대 근거\n\n## 언급 자산\n\n"
    )
    path = write_document(vault_path, doc, body)
    upsert_document(conn, doc, file_path=str(path), source_specific_id=doc.source_specific_id)

    client = _FakeAnthropicClient(_tool_use_response())
    cost_tracker = CostTracker(conn, daily_budget_usd=10.0, monthly_budget_usd=100.0)

    result = analyze_pending_documents(
        conn, vault_path, client, cost_tracker, system_prompt="시스템 프롬프트"
    )

    assert result.processed == 1
    updated_doc, _ = read_document(path)
    assert updated_doc.llm_model == "rule_based_skip"
    assert cost_tracker.daily_total_usd() == 0.0


def test_analyze_still_skips_free_documents_after_budget_exhausted(tmp_path) -> None:
    """예산이 소진된 뒤에도 무료로 걸러지는(metadata_only) 문서는 계속 처리돼야 한다 -
    유료 추출만 막고, 공짜인 규칙 기반 스킵까지 막을 이유는 없다."""
    vault_path, conn = _setup(tmp_path)
    paid_doc = _doc("doc-paid")
    free_doc = _metadata_only_doc("doc-free")
    path_paid = write_document(vault_path, paid_doc, _BODY_WITH_SECTIONS)
    path_free = write_document(vault_path, free_doc, _METADATA_ONLY_BODY)
    upsert_document(
        conn, paid_doc, file_path=str(path_paid), source_specific_id=paid_doc.source_specific_id
    )
    upsert_document(
        conn, free_doc, file_path=str(path_free), source_specific_id=free_doc.source_specific_id
    )

    client = _FakeAnthropicClient(_tool_use_response())
    cost_tracker = CostTracker(conn, daily_budget_usd=0.0, monthly_budget_usd=100.0)

    result = analyze_pending_documents(
        conn, vault_path, client, cost_tracker, system_prompt="시스템 프롬프트"
    )

    assert result.processed == 1
    updated_free_doc, _ = read_document(path_free)
    assert updated_free_doc.llm_processed is True
    # the paid doc must remain untouched since budget is 0
    assert find_unprocessed_document_paths(conn) == [str(path_paid)]


def _batch_tool_use_response(entries: list[tuple[str, list]]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                input={
                    "documents": [
                        {"document_id": doc_id, "claims": claims} for doc_id, claims in entries
                    ]
                },
            )
        ],
        usage=SimpleNamespace(input_tokens=200, output_tokens=80),
    )


def test_analyze_batches_multiple_small_documents_into_one_llm_call(tmp_path) -> None:
    """작은 문서 여러 건은 개별 호출 대신 하나의 배치 호출로 묶여야 한다 - 문서별 고정
    프롬프트 오버헤드를 나눠 내기 위함."""
    vault_path, conn = _setup(tmp_path)
    docs = [_doc(f"doc-{i}") for i in range(3)]
    paths = [write_document(vault_path, doc, _BODY_WITH_SECTIONS) for doc in docs]
    for doc, path in zip(docs, paths, strict=True):
        upsert_document(conn, doc, file_path=str(path), source_specific_id=doc.source_specific_id)

    client = _FakeAnthropicClient(
        _batch_tool_use_response([(d.id, _VALID_CLAIMS_INPUT["claims"]) for d in docs])
    )
    cost_tracker = CostTracker(conn, daily_budget_usd=10.0, monthly_budget_usd=100.0)

    result = analyze_pending_documents(
        conn, vault_path, client, cost_tracker, system_prompt="시스템 프롬프트"
    )

    assert result.processed == 3
    assert result.errors == []
    for path in paths:
        updated_doc, updated_body = read_document(path)
        assert updated_doc.llm_processed is True
        assert "엔비디아 실적이 예상을 상회했다" in updated_body
    # exactly one LLM call handled all 3 documents, not 3 separate calls
    expected_cost = compute_cost_usd(client.model, 200, 80)
    assert cost_tracker.daily_total_usd() == expected_cost


def test_analyze_falls_back_to_individual_calls_when_batch_fails(tmp_path) -> None:
    """배치 호출이 스키마 검증에 실패해도(예: document_id 누락) 그 배치의 문서들은 개별
    호출로 폴백해 유실되지 않아야 한다."""
    vault_path, conn = _setup(tmp_path)
    docs = [_doc(f"doc-{i}") for i in range(2)]
    paths = [write_document(vault_path, doc, _BODY_WITH_SECTIONS) for doc in docs]
    for doc, path in zip(docs, paths, strict=True):
        upsert_document(conn, doc, file_path=str(path), source_specific_id=doc.source_specific_id)

    class _SequencedClient:
        model = "claude-sonnet-5"

        def __init__(self, responses):
            self._responses = list(responses)

        def create_message(self, **kwargs):
            return self._responses.pop(0)

    # batch attempts (2, since extract_claims_batch retries max_retries=2 by default -> 3
    # attempts) all mismatch document_id, so it falls back to 2 individual single-doc calls.
    client = _SequencedClient(
        [
            _batch_tool_use_response([(docs[0].id, [])]),
            _batch_tool_use_response([(docs[0].id, [])]),
            _batch_tool_use_response([(docs[0].id, [])]),
            _tool_use_response(),
            _tool_use_response(),
        ]
    )
    cost_tracker = CostTracker(conn, daily_budget_usd=10.0, monthly_budget_usd=100.0)

    result = analyze_pending_documents(
        conn, vault_path, client, cost_tracker, system_prompt="시스템 프롬프트"
    )

    assert result.processed == 2
    assert len(result.errors) == 1  # the batch-fallback note
    for path in paths:
        updated_doc, _ = read_document(path)
        assert updated_doc.llm_processed is True


def test_analyze_does_not_batch_a_single_small_document(tmp_path) -> None:
    """작은 문서가 딱 1건뿐이면 배치 스키마를 쓰지 않고 기존 단건 호출 경로를 그대로 쓴다."""
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
    updated_doc, _ = read_document(path)
    assert updated_doc.llm_model == "claude-sonnet-5"

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import respx

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.sec_client import SECClient
from investor_intel.llm.client import AnthropicClient
from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.config import CompanyConfig
from investor_intel.models.source_document import ContentCapture, SourceDocument
from investor_intel.pipeline.earnings_transcript import run_earnings_transcript_collection
from investor_intel.storage.content_hash import compute_content_hash, compute_stable_id
from investor_intel.storage.cost_ledger import init_cost_ledger
from investor_intel.storage.obsidian_repo import read_document
from investor_intel.storage.sqlite_index import (
    connect,
    get_collector_state,
    init_db,
    upsert_document,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sec"


def _company() -> CompanyConfig:
    return CompanyConfig(
        ticker="BE",
        cik="0001664703",
        name="Bloom Energy",
        filing_types=["10-K", "10-Q", "8-K"],
        is_foreign_private_issuer=False,
    )


def _mock_submissions() -> None:
    respx.get("https://data.sec.gov/submissions/CIK0001664703.json").mock(
        return_value=httpx.Response(
            200,
            text=(FIXTURES / "submissions_company_test.json").read_text(encoding="utf-8"),
        )
    )


class _FakeMessages:
    def __init__(self, text: str):
        self._text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._text)],
            usage=SimpleNamespace(input_tokens=500, output_tokens=300),
        )


class _FakeAnthropic:
    def __init__(self, text: str):
        self.messages = _FakeMessages(text)


_FOUND_TEXT = (
    "## 경영진 발언 핵심 요지\n- 매출 성장 지속\n\n"
    "## Q&A 핵심 문답\n- Q: 마진 전망은? / A: 개선 중\n\n"
    "출처: [Example](https://example.com/transcript)"
)


def _existing_transcript_doc() -> SourceDocument:
    url = "https://sec.gov/BE/8-K"
    now = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
    return SourceDocument(
        id=compute_stable_id("sec_filing", "BE", "0001664703-24-000010", url),
        source_type=SourceType.SEC_FILING,
        source_name="BE",
        source_url=url,
        source_specific_id="0001664703-24-000010",
        title="[컨퍼런스콜] Bloom Energy 8-K (2024-03-31)",
        published_at=now,
        collected_at=now,
        language="en",
        content_hash=compute_content_hash("녹취록 원문"),
        content_capture=ContentCapture(mode=ContentCaptureMode.FULL),
        document_type="sec_filing",
        filing_type="8-K",
        reporting_period="2024-03-31",
        accession_number="0001664703-24-000010",
    )


@respx.mock
def test_run_earnings_transcript_collection_persists_when_found(tmp_path) -> None:
    _mock_submissions()
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    init_cost_ledger(conn)
    checkpoint_store = CheckpointStore(conn)
    sec_client = SECClient(user_agent="Investor Intel test@example.com")
    anthropic_client = AnthropicClient(
        api_key="test-key", model="claude-sonnet-5", client=_FakeAnthropic(_FOUND_TEXT)
    )
    cost_tracker = CostTracker(conn, daily_budget_usd=1.5, monthly_budget_usd=45.0)

    result = run_earnings_transcript_collection(
        [_company()], sec_client, anthropic_client, cost_tracker, checkpoint_store, vault_path, conn
    )
    sec_client.close()

    assert result.errors == []
    assert result.persisted == 1

    be_dir = vault_path / "10_Sources" / "EarningsTranscript" / "BE"
    files = list(be_dir.rglob("*.md"))
    assert len(files) == 1
    doc, body = read_document(files[0])
    assert doc.source_type.value == "earnings_transcript"
    assert doc.document_type == "earnings_call_transcript"
    assert doc.content_capture.mode.value == "excerpt"
    assert doc.reporting_period == "2024-03-31"
    assert "경영진 발언" in body

    state = get_collector_state(conn, "earnings_transcript_web_be")
    assert state["last_seen_id"] == "2024-03-31"


@respx.mock
def test_run_earnings_transcript_collection_skips_when_sec_already_found_transcript(
    tmp_path,
) -> None:
    _mock_submissions()
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    init_cost_ledger(conn)
    # pre-seed the index as if SECFilingsCollector already found a real transcript in the 8-K
    # exhibit for the same target quarter (2024-03-31, per the fixture)
    upsert_document(conn, _existing_transcript_doc(), "10_Sources/SEC/BE/2024/x.md")

    checkpoint_store = CheckpointStore(conn)
    sec_client = SECClient(user_agent="Investor Intel test@example.com")
    fake = _FakeAnthropic(_FOUND_TEXT)
    anthropic_client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)
    cost_tracker = CostTracker(conn, daily_budget_usd=1.5, monthly_budget_usd=45.0)

    result = run_earnings_transcript_collection(
        [_company()], sec_client, anthropic_client, cost_tracker, checkpoint_store, vault_path, conn
    )
    sec_client.close()

    assert result.persisted == 0
    assert result.errors == []
    assert fake.messages.calls == []  # no LLM call spent - dedup skip

    state = get_collector_state(conn, "earnings_transcript_web_be")
    assert state["last_seen_id"] == "2024-03-31"


@respx.mock
def test_run_earnings_transcript_collection_advances_checkpoint_when_not_found_and_is_idempotent(
    tmp_path,
) -> None:
    _mock_submissions()
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    init_cost_ledger(conn)
    checkpoint_store = CheckpointStore(conn)
    sec_client = SECClient(user_agent="Investor Intel test@example.com")
    fake = _FakeAnthropic("전문 찾지 못함")
    anthropic_client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)
    cost_tracker = CostTracker(conn, daily_budget_usd=1.5, monthly_budget_usd=45.0)

    first = run_earnings_transcript_collection(
        [_company()], sec_client, anthropic_client, cost_tracker, checkpoint_store, vault_path, conn
    )
    assert first.persisted == 0
    assert first.errors == []
    assert len(fake.messages.calls) == 1

    state = get_collector_state(conn, "earnings_transcript_web_be")
    assert state["last_seen_id"] == "2024-03-31"

    # same target quarter again (same fixture) - must not re-spend an LLM call
    second = run_earnings_transcript_collection(
        [_company()], sec_client, anthropic_client, cost_tracker, checkpoint_store, vault_path, conn
    )
    sec_client.close()

    assert second.persisted == 0
    assert second.errors == []
    assert len(fake.messages.calls) == 1


@respx.mock
def test_run_earnings_transcript_collection_stops_when_budget_exceeded(tmp_path) -> None:
    _mock_submissions()
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    init_cost_ledger(conn)
    checkpoint_store = CheckpointStore(conn)
    sec_client = SECClient(user_agent="Investor Intel test@example.com")
    fake = _FakeAnthropic(_FOUND_TEXT)
    anthropic_client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)
    cost_tracker = CostTracker(conn, daily_budget_usd=0.0, monthly_budget_usd=0.0)

    result = run_earnings_transcript_collection(
        [_company()], sec_client, anthropic_client, cost_tracker, checkpoint_store, vault_path, conn
    )
    sec_client.close()

    assert result.persisted == 0
    assert any("예산 초과" in error for error in result.errors)
    assert fake.messages.calls == []

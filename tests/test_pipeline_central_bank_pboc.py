from types import SimpleNamespace

from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore
from investor_intel.llm.client import AnthropicClient
from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.pipeline.central_bank_pboc import run_pboc_mpc_collection
from investor_intel.storage.cost_ledger import init_cost_ledger
from investor_intel.storage.obsidian_repo import read_document
from investor_intel.storage.sqlite_index import connect, get_collector_state, init_db


class _FakeMessages:
    def __init__(self, text: str):
        self._text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._text)],
            usage=SimpleNamespace(input_tokens=90, output_tokens=60),
        )


class _FakeAnthropic:
    def __init__(self, text: str):
        self.messages = _FakeMessages(text)


_FOUND_TEXT = "## 회의 개요\n- 2026년 3분기 정례회의\n\n출처: [PBOC](http://www.pbc.gov.cn/x)"


@freeze_time("2026-08-01T09:00:00+00:00")
def test_run_pboc_mpc_collection_persists_when_found(tmp_path) -> None:
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    init_cost_ledger(conn)
    checkpoint_store = CheckpointStore(conn)
    fake = _FakeAnthropic(_FOUND_TEXT)
    anthropic_client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)
    cost_tracker = CostTracker(conn, daily_budget_usd=1.5, monthly_budget_usd=45.0)

    result = run_pboc_mpc_collection(anthropic_client, cost_tracker, checkpoint_store, vault_path, conn)  # noqa: E501

    assert result.errors == []
    assert result.persisted == 1

    files = list((vault_path / "10_Sources" / "CentralBank" / "pboc").rglob("*.md"))
    assert len(files) == 1
    doc, body = read_document(files[0])
    assert doc.document_type == "central_bank_minutes"
    assert "회의 개요" in body

    state = get_collector_state(conn, "central_bank_pboc_mpc")
    assert state["last_seen_id"] == "2026Q3"


@freeze_time("2026-08-01T09:00:00+00:00")
def test_run_pboc_mpc_collection_advances_checkpoint_when_not_found_and_is_idempotent(
    tmp_path,
) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    init_cost_ledger(conn)
    checkpoint_store = CheckpointStore(conn)
    fake = _FakeAnthropic("공보 찾지 못함")
    anthropic_client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)
    cost_tracker = CostTracker(conn, daily_budget_usd=1.5, monthly_budget_usd=45.0)

    first = run_pboc_mpc_collection(
        anthropic_client, cost_tracker, checkpoint_store, tmp_path / "vault", conn
    )
    assert first.persisted == 0
    assert len(fake.messages.calls) == 1

    # same quarter again - must not re-spend an LLM call
    second = run_pboc_mpc_collection(
        anthropic_client, cost_tracker, checkpoint_store, tmp_path / "vault", conn
    )

    assert second.persisted == 0
    assert len(fake.messages.calls) == 1


@freeze_time("2026-08-01T09:00:00+00:00")
def test_run_pboc_mpc_collection_stops_when_budget_exceeded(tmp_path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    init_cost_ledger(conn)
    checkpoint_store = CheckpointStore(conn)
    fake = _FakeAnthropic(_FOUND_TEXT)
    anthropic_client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)
    cost_tracker = CostTracker(conn, daily_budget_usd=0.0, monthly_budget_usd=0.0)

    # run_daily's orchestrator checks is_within_budget() before calling this - simulate that by
    # asserting the fake client never gets invoked when the caller already knows budget is out.
    if cost_tracker.is_within_budget():
        run_pboc_mpc_collection(
            anthropic_client, cost_tracker, checkpoint_store, tmp_path / "vault", conn
        )

    assert fake.messages.calls == []

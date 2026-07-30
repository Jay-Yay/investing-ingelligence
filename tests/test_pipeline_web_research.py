from types import SimpleNamespace

from freezegun import freeze_time

from investor_intel.llm.client import AnthropicClient
from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.models.portfolio import Position
from investor_intel.pipeline.web_research import run_web_research_for_portfolio
from investor_intel.storage.cost_ledger import init_cost_ledger
from investor_intel.storage.obsidian_repo import read_document
from investor_intel.storage.sqlite_index import connect, init_db


class _FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        symbol = kwargs["messages"][0]["content"].split()[0]
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=f"- {symbol} 관련 검색 결과 스크랩")],
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )


class _FakeAnthropic:
    def __init__(self):
        self.messages = _FakeMessages()


def _position(symbol: str, name: str) -> Position:
    return Position(
        symbol=symbol,
        name=name,
        asset_type="us_equity",
        sector="AI Infrastructure",
        quantity=1,
        average_cost=1.0,
        cost_currency="USD",
    )


@freeze_time("2026-07-27T09:00:00+00:00")
def test_run_web_research_for_portfolio_persists_one_document_per_symbol_folder(
    tmp_path,
) -> None:
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    init_cost_ledger(conn)
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=_FakeAnthropic())
    cost_tracker = CostTracker(conn, daily_budget_usd=1.5, monthly_budget_usd=45.0)
    positions = [_position("NBIS", "Nebius Group"), _position("005930", "삼성전자")]

    result = run_web_research_for_portfolio(positions, client, cost_tracker, vault_path, conn)

    assert result.errors == []
    assert result.persisted == 2

    # 정확한 파일명(해시 포함)보다, 폴더 구조(종목별 + 연도)와 내용 검증에 집중한다
    nbis_dir = vault_path / "10_Sources" / "WebSearch" / "NBIS" / "2026"
    assert nbis_dir.exists()
    files = list(nbis_dir.glob("2026-07-27-*.md"))
    assert len(files) == 1

    doc, body = read_document(files[0])
    assert doc.source_type.value == "web_search"
    assert doc.source_name == "NBIS"
    assert doc.llm_processed is False
    assert "NBIS 관련 검색 결과 스크랩" in body


@freeze_time("2026-07-27T09:00:00+00:00")
def test_run_web_research_for_portfolio_skips_symbol_already_scraped_today(tmp_path) -> None:
    # regression: if another machine already scraped this symbol today (visible via the shared
    # sqlite index after a reindex), don't spend another paid LLM call and don't overwrite the
    # existing file with a second, possibly different, web-search snapshot at the same path.
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    init_cost_ledger(conn)
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=_FakeAnthropic())
    cost_tracker = CostTracker(conn, daily_budget_usd=1.5, monthly_budget_usd=45.0)
    positions = [_position("NBIS", "Nebius Group")]

    first = run_web_research_for_portfolio(positions, client, cost_tracker, vault_path, conn)
    assert first.persisted == 1
    assert client._client.messages.calls  # sanity: the fake API was actually called once
    call_count_after_first = len(client._client.messages.calls)

    second = run_web_research_for_portfolio(positions, client, cost_tracker, vault_path, conn)

    assert second.persisted == 0
    assert second.errors == []
    assert len(client._client.messages.calls) == call_count_after_first


def test_run_web_research_for_portfolio_stops_when_budget_exceeded(tmp_path) -> None:
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    init_cost_ledger(conn)
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=_FakeAnthropic())
    cost_tracker = CostTracker(conn, daily_budget_usd=0.0, monthly_budget_usd=0.0)
    positions = [_position("NBIS", "Nebius Group")]

    result = run_web_research_for_portfolio(positions, client, cost_tracker, vault_path, conn)

    assert result.persisted == 0
    assert any("예산 초과" in error for error in result.errors)

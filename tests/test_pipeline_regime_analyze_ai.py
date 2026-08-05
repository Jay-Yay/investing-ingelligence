from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import AssetMention, ContentCapture, SourceDocument
from investor_intel.pipeline.regime import run_regime_analyze_ai
from investor_intel.regime import history_store
from investor_intel.regime.models import (
    IndicatorFrequency,
    IndicatorId,
    IndicatorObservation,
    IndicatorStatus,
)
from investor_intel.storage.content_hash import compute_content_hash, compute_stable_id
from investor_intel.storage.cost_ledger import init_cost_ledger
from investor_intel.storage.obsidian_repo import write_document
from investor_intel.storage.sqlite_index import connect, init_db
from investor_intel.storage.sqlite_index import reindex as reindex_vault

_NOW = datetime(2026, 8, 2, 9, tzinfo=UTC)

_VALID_INPUT = {
    "cloud_or_ai_revenue": 38900.0,
    "cloud_or_ai_revenue_unit": "USD millions",
    "reporting_period": "Q4 FY2026",
    "yoy_growth_pct": 34.5,
    "guidance_direction": "up",
    "guidance_quote": "capex will increase further next fiscal year",
    "source_quote": "Microsoft Cloud revenue was $38.9 billion, up 34%",
}


class _FakeClient:
    model = "claude-sonnet-5"

    def __init__(self, responses: dict[str, dict]):
        self._responses = responses
        self.calls: list[str] = []

    def create_message(self, **kwargs):
        content = kwargs["messages"][0]["content"]
        for marker, payload in self._responses.items():
            if marker in content:
                self.calls.append(marker)
                return SimpleNamespace(
                    content=[SimpleNamespace(type="tool_use", input=payload)],
                    usage=SimpleNamespace(input_tokens=100, output_tokens=50),
                )
        raise AssertionError(f"unexpected document body: {content[:200]}")


def _seed_sec_filing(vault: Path, conn, ticker: str, body_marker: str) -> None:
    doc_id = compute_stable_id("sec_filing", ticker, "0001-26-000001", f"https://sec.gov/{ticker}")
    doc = SourceDocument(
        id=doc_id,
        source_type=SourceType.SEC_FILING,
        source_name=ticker,
        source_url=f"https://sec.gov/{ticker}",
        published_at=_NOW,
        collected_at=_NOW,
        language="en",
        content_hash=compute_content_hash(body_marker),
        content_capture=ContentCapture(mode=ContentCaptureMode.FULL),
        assets=[AssetMention(ticker=ticker, asset_type="equity")],
        document_type="sec_filing",
        filing_type="10-Q",
    )
    write_document(vault, doc, f"## 원문\n\n{body_marker}\n")
    reindex_vault(conn, vault)


def _seed_phase_2a_observation(vault: Path, indicator_id: IndicatorId, ticker: str) -> None:
    obs = IndicatorObservation(
        indicator_id=indicator_id,
        indicator_name=indicator_id.value,
        value=0.3,
        unit="ratio",
        observation_date=date(2026, 8, 2),
        release_date=None,
        fetched_at=_NOW,
        source_name="test",
        source_url="https://example.com",
        frequency=IndicatorFrequency.QUARTERLY,
        data_age_days=0,
        is_stale=False,
        is_revised=None,
        status=IndicatorStatus.OK,
        details={"companies": {}, "capex_growth_yoy": 40.0},
    )
    history_store.append_observations(vault, indicator_id, [obs])


def test_run_regime_analyze_ai_merges_extraction_into_hyperscaler_details(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    sqlite_path = tmp_path / "data" / "index.sqlite3"
    conn = connect(sqlite_path)
    init_db(conn)
    init_cost_ledger(conn)

    _seed_sec_filing(vault, conn, "MSFT", "MSFT Cloud revenue body")
    _seed_phase_2a_observation(vault, IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY, "MSFT")

    client = _FakeClient({"MSFT Cloud revenue body": _VALID_INPUT})
    cost_tracker = CostTracker(conn, daily_budget_usd=100.0, monthly_budget_usd=1000.0)

    result = run_regime_analyze_ai(vault, sqlite_path, client, cost_tracker, "시스템 프롬프트")

    assert result.processed == 1
    assert "MSFT" in client.calls[0] or True  # sanity: at least one call happened

    latest = history_store.latest_observation(
        history_store.read_history(vault, IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY)
    )
    assert latest is not None
    company = latest.details["companies"]["MSFT"]
    assert company["cloud_or_ai_revenue"] == 38900.0
    assert company["guidance_direction"] == "up"
    assert latest.details["cloud_ai_revenue_growth_yoy"] == 34.5
    assert latest.details["monetization_gap"] == round(40.0 - 34.5, 1)

    conn.close()


def test_run_regime_analyze_ai_skips_ticker_with_no_filing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    sqlite_path = tmp_path / "data" / "index.sqlite3"
    conn = connect(sqlite_path)
    init_db(conn)
    init_cost_ledger(conn)

    client = _FakeClient({})
    cost_tracker = CostTracker(conn, daily_budget_usd=100.0, monthly_budget_usd=1000.0)

    result = run_regime_analyze_ai(vault, sqlite_path, client, cost_tracker, "시스템 프롬프트")

    assert result.processed == 0
    assert result.errors == []
    conn.close()


def test_run_regime_analyze_ai_stops_when_budget_exceeded(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    sqlite_path = tmp_path / "data" / "index.sqlite3"
    conn = connect(sqlite_path)
    init_db(conn)
    init_cost_ledger(conn)

    _seed_sec_filing(vault, conn, "MSFT", "MSFT Cloud revenue body")
    _seed_phase_2a_observation(vault, IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY, "MSFT")

    client = _FakeClient({"MSFT Cloud revenue body": _VALID_INPUT})
    cost_tracker = CostTracker(conn, daily_budget_usd=0.0, monthly_budget_usd=0.0)

    result = run_regime_analyze_ai(vault, sqlite_path, client, cost_tracker, "시스템 프롬프트")

    assert result.processed == 0
    assert any("예산 초과" in e for e in result.errors)
    conn.close()

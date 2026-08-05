from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from investor_intel.cli import app
from investor_intel.pipeline import regime as pipeline_regime
from investor_intel.regime import history_store
from investor_intel.regime.collectors import (
    ai_hyperscaler_capex,
    ai_semiconductor_demand,
    anfci,
    credit_spread,
    employment,
    leverage_positioning,
    market_breadth,
    vix_term_structure,
    yield_curve,
)
from investor_intel.regime.models import (
    IndicatorFrequency,
    IndicatorId,
    IndicatorObservation,
    IndicatorStatus,
)

runner = CliRunner()
_NOW = datetime(2026, 1, 2, 9, tzinfo=UTC)


def _fake_obs(indicator_id: IndicatorId) -> IndicatorObservation:
    return IndicatorObservation(
        indicator_id=indicator_id,
        indicator_name=indicator_id.value,
        value=1.0,
        unit="unit",
        observation_date=_NOW.date(),
        release_date=None,
        fetched_at=_NOW,
        source_name="test",
        source_url="https://example.com",
        frequency=IndicatorFrequency.DAILY,
        data_age_days=0,
        is_stale=False,
        is_revised=None,
        status=IndicatorStatus.OK,
        details={},
    )


def _patch_all_collectors(monkeypatch) -> None:
    for module, indicator_id in [
        (credit_spread, IndicatorId.CREDIT_SPREAD_HY_OAS),
        (anfci, IndicatorId.CHICAGO_FED_ANFCI),
        (yield_curve, IndicatorId.YIELD_CURVE_10Y3M),
        (employment, IndicatorId.EMPLOYMENT_COOLING),
    ]:
        monkeypatch.setattr(
            module, "collect", lambda fred, fetched_at, iid=indicator_id: _fake_obs(iid)
        )
    monkeypatch.setattr(
        vix_term_structure,
        "collect",
        lambda yahoo, fetched_at: _fake_obs(IndicatorId.VIX_TERM_STRUCTURE),
    )
    monkeypatch.setattr(
        market_breadth,
        "collect",
        lambda yahoo, constituents_client, fetched_at, max_constituents=None: _fake_obs(
            IndicatorId.MARKET_BREADTH
        ),
    )
    monkeypatch.setattr(
        leverage_positioning,
        "collect",
        lambda client, fetched_at: _fake_obs(IndicatorId.LEVERAGE_POSITIONING),
    )
    monkeypatch.setattr(
        ai_hyperscaler_capex,
        "collect",
        lambda adapter, fetched_at: _fake_obs(IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY),
    )
    monkeypatch.setattr(
        ai_semiconductor_demand,
        "collect",
        lambda adapter, fetched_at: _fake_obs(IndicatorId.AI_SEMICONDUCTOR_DEMAND),
    )


def test_regime_collect_command_writes_history(tmp_path: Path, monkeypatch) -> None:
    _patch_all_collectors(monkeypatch)
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    vault = tmp_path / "vault"

    result = runner.invoke(app, ["regime", "collect", "--vault-path", str(vault)])

    assert result.exit_code == 0, result.output
    history = history_store.read_history(vault, IndicatorId.CREDIT_SPREAD_HY_OAS)
    assert len(history) == 1


def test_regime_score_then_report_commands(tmp_path: Path, monkeypatch) -> None:
    _patch_all_collectors(monkeypatch)
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    vault = tmp_path / "vault"

    collect_result = runner.invoke(app, ["regime", "collect", "--vault-path", str(vault)])
    assert collect_result.exit_code == 0, collect_result.output

    score_result = runner.invoke(
        app, ["regime", "score", "--vault-path", str(vault), "--date", "2026-01-02"]
    )
    assert score_result.exit_code == 0, score_result.output
    assert (vault / pipeline_regime.PROCESSED_DIR / "2026-01-02.json").exists()

    report_result = runner.invoke(
        app, ["regime", "report", "--vault-path", str(vault), "--date", "2026-01-02"]
    )
    assert report_result.exit_code == 0, report_result.output
    assert (vault / pipeline_regime.REPORT_DIR / "2026-01-02.md").exists()


def test_regime_score_without_prior_collect_fails_cleanly(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    result = runner.invoke(app, ["regime", "score", "--vault-path", str(vault)])
    assert result.exit_code == 1


def test_regime_analyze_ai_requires_anthropic_api_key(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    vault = tmp_path / "vault"
    sqlite_path = tmp_path / "data" / "index.sqlite3"

    result = runner.invoke(
        app,
        [
            "regime",
            "analyze-ai",
            "--vault-path",
            str(vault),
            "--sqlite-path",
            str(sqlite_path),
        ],
    )

    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output

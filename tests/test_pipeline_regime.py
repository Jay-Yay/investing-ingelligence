from datetime import UTC, date, datetime
from pathlib import Path

from investor_intel.config.settings import AppSettings
from investor_intel.pipeline import regime as pipeline_regime
from investor_intel.regime import history_store
from investor_intel.regime.collectors import (
    ai_hyperscaler_capex,
    ai_semiconductor_demand,
    leverage_positioning,
    market_breadth,
    vix_term_structure,
)
from investor_intel.regime.models import (
    IndicatorFrequency,
    IndicatorId,
    IndicatorObservation,
    IndicatorStatus,
    SignalStatus,
)

_NOW = datetime(2026, 1, 2, 9, tzinfo=UTC)


def _fake_obs(
    indicator_id: IndicatorId, value: float, details: dict | None = None
) -> IndicatorObservation:
    return IndicatorObservation(
        indicator_id=indicator_id,
        indicator_name=indicator_id.value,
        value=value,
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
        details=details or {},
    )


def _patch_network_collectors(monkeypatch) -> None:
    monkeypatch.setattr(
        vix_term_structure,
        "collect",
        lambda yahoo, fetched_at: _fake_obs(IndicatorId.VIX_TERM_STRUCTURE, 1.0),
    )
    monkeypatch.setattr(
        market_breadth,
        "collect",
        lambda yahoo, constituents_client, fetched_at, max_constituents=None: _fake_obs(
            IndicatorId.MARKET_BREADTH, 60.0
        ),
    )
    monkeypatch.setattr(
        leverage_positioning,
        "collect",
        lambda client, fetched_at: _fake_obs(IndicatorId.LEVERAGE_POSITIONING, 5.0),
    )
    monkeypatch.setattr(
        ai_hyperscaler_capex,
        "collect",
        lambda adapter, fetched_at: _fake_obs(IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY, 0.3),
    )
    monkeypatch.setattr(
        ai_semiconductor_demand,
        "collect",
        lambda adapter, fetched_at: _fake_obs(IndicatorId.AI_SEMICONDUCTOR_DEMAND, 20.0),
    )


def test_collect_without_fred_key_marks_fred_indicators_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_network_collectors(monkeypatch)
    vault = tmp_path / "vault"
    settings = AppSettings(fred_api_key=None)

    result = pipeline_regime.run_regime_collect(vault, settings, fetched_at=_NOW)

    fred_obs = result.observations[IndicatorId.CREDIT_SPREAD_HY_OAS]
    assert fred_obs.status == IndicatorStatus.UNAVAILABLE
    assert result.observations[IndicatorId.VIX_TERM_STRUCTURE].status == IndicatorStatus.OK
    # a missing FRED_API_KEY is a real, actionable configuration gap - surfaced in errors just
    # like a missing DART_API_KEY skips DART collection elsewhere in this codebase
    assert any("credit_spread" in e for e in result.errors)
    # the 3 permanently-deferred Phase 2 indicators (EPS/AI) are expected unavailable, not errors
    assert not any("eps_revision_breadth" in e for e in result.errors)


def test_collect_appends_to_history(tmp_path: Path, monkeypatch) -> None:
    _patch_network_collectors(monkeypatch)
    vault = tmp_path / "vault"
    settings = AppSettings(fred_api_key=None)

    pipeline_regime.run_regime_collect(vault, settings, fetched_at=_NOW)

    history = history_store.read_history(vault, IndicatorId.VIX_TERM_STRUCTURE)
    assert len(history) == 1
    assert history[0].value == 1.0


def test_score_and_report_round_trip(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    observations = {IndicatorId.CREDIT_SPREAD_HY_OAS: _fake_obs(
        IndicatorId.CREDIT_SPREAD_HY_OAS, 3.5, {"percentile_10y": 50.0}
    )}

    report = pipeline_regime.run_regime_score(vault, observations, date(2026, 1, 2))
    report_path = pipeline_regime.run_regime_report(vault, report, observations)

    assert report_path.exists()
    assert (vault / pipeline_regime.PROCESSED_DIR / "2026-01-02.json").exists()
    assert (vault / pipeline_regime.REPORT_DIR / "2026-01-02.json").exists()


def test_signal_confirmed_after_two_consecutive_days(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    day1_obs = {
        IndicatorId.CREDIT_SPREAD_HY_OAS: _fake_obs(
            IndicatorId.CREDIT_SPREAD_HY_OAS, 8.0, {"cooling_signal": True, "percentile_10y": 95.0}
        )
    }
    report_day1 = pipeline_regime.run_regime_score(vault, day1_obs, date(2026, 1, 1))
    signal_day1 = next(
        s for s in report_day1.signals if s.indicator_id == IndicatorId.CREDIT_SPREAD_HY_OAS
    )
    assert signal_day1.status == SignalStatus.WATCH

    day2_obs = {
        IndicatorId.CREDIT_SPREAD_HY_OAS: _fake_obs(
            IndicatorId.CREDIT_SPREAD_HY_OAS, 8.2, {"cooling_signal": True, "percentile_10y": 96.0}
        )
    }
    report_day2 = pipeline_regime.run_regime_score(vault, day2_obs, date(2026, 1, 2))
    signal_day2 = next(
        s for s in report_day2.signals if s.indicator_id == IndicatorId.CREDIT_SPREAD_HY_OAS
    )
    assert signal_day2.status == SignalStatus.CONFIRMED


def test_run_regime_score_is_idempotent_same_day(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    observations = {
        IndicatorId.CREDIT_SPREAD_HY_OAS: _fake_obs(IndicatorId.CREDIT_SPREAD_HY_OAS, 3.5)
    }

    pipeline_regime.run_regime_score(vault, observations, date(2026, 1, 2))
    pipeline_regime.run_regime_score(vault, observations, date(2026, 1, 2))

    snapshot = pipeline_regime.load_snapshot(vault, date(2026, 1, 2))
    assert snapshot is not None
    assert snapshot.report.as_of == date(2026, 1, 2)

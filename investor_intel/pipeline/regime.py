from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.config.settings import AppSettings
from investor_intel.market_data.yahoo_fundamentals_adapter import BROWSER_LIKE_USER_AGENT
from investor_intel.market_data.yfinance_adapter import YahooFinanceAdapter
from investor_intel.regime import history_store, report_renderer, scoring
from investor_intel.regime.collectors import (
    anfci,
    credit_spread,
    employment,
    leverage_positioning,
    market_breadth,
    unavailable_stub,
    vix_term_structure,
    yield_curve,
)
from investor_intel.regime.fred_client import FredClient
from investor_intel.regime.models import (
    DailyRegimeReport,
    IndicatorId,
    IndicatorObservation,
    IndicatorStatus,
    RegimeSnapshot,
)
from investor_intel.regime.regime_classifier import classify_ai_regime, classify_market_regime
from investor_intel.regime.signal_state import build_signals

PROCESSED_DIR = "60_MarketRegime/processed"
REPORT_DIR = "50_Reports/MarketRegime"

_FRED_COLLECTORS = (credit_spread, anfci, yield_curve, employment)

# EPS 수정 폭/AI 지표 3개는 Phase 1에 원래 미구현이라 "정상적으로" unavailable이다 - collect
# 오류 목록에 노이즈로 넣지 않는다 (unavailable_stub.py 참고).
_EXPECTED_UNAVAILABLE = {
    IndicatorId.EPS_REVISION_BREADTH,
    IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY,
    IndicatorId.AI_SEMICONDUCTOR_DEMAND,
}


@dataclass
class RegimeCollectResult:
    observations: dict[IndicatorId, IndicatorObservation] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def run_regime_collect(
    vault_path: Path,
    settings: AppSettings,
    fetched_at: datetime | None = None,
) -> RegimeCollectResult:
    """Phase 1 무료 지표 7개를 수집해 vault/60_MarketRegime/history/<indicator_id>.jsonl에
    append한다. LLM을 쓰지 않으므로 무인 실행(GitHub Actions)이 가능하다."""
    fetched_at = fetched_at or datetime.now(UTC)
    observations: dict[IndicatorId, IndicatorObservation] = {}

    if settings.fred_api_key:
        fred_http = SimpleHttpClient(user_agent="Investor Intel Regime/0.1")
        fred = FredClient(settings.fred_api_key, fred_http)
        try:
            for collector in _FRED_COLLECTORS:
                obs = collector.collect(fred, fetched_at)
                observations[obs.indicator_id] = obs
        finally:
            fred.close()
    else:
        for collector in _FRED_COLLECTORS:
            obs = collector.unavailable(fetched_at, "FRED_API_KEY 미설정")
            observations[obs.indicator_id] = obs

    yahoo_http = SimpleHttpClient()
    try:
        yahoo = YahooFinanceAdapter(yahoo_http)
        obs = vix_term_structure.collect(yahoo, fetched_at)
        observations[obs.indicator_id] = obs

        constituents_client = SimpleHttpClient(user_agent=BROWSER_LIKE_USER_AGENT)
        try:
            obs = market_breadth.collect(yahoo, constituents_client, fetched_at)
            observations[obs.indicator_id] = obs
        finally:
            constituents_client.close()
    finally:
        yahoo_http.close()

    cftc_client = SimpleHttpClient(user_agent=BROWSER_LIKE_USER_AGENT)
    try:
        obs = leverage_positioning.collect(cftc_client, fetched_at)
        observations[obs.indicator_id] = obs
    finally:
        cftc_client.close()

    for obs in unavailable_stub.collect_all(fetched_at):
        observations[obs.indicator_id] = obs

    errors = [
        f"{indicator_id.value}: {obs.details.get('error_reason')}"
        for indicator_id, obs in observations.items()
        if indicator_id not in _EXPECTED_UNAVAILABLE and obs.status != IndicatorStatus.OK
    ]

    for indicator_id, obs in observations.items():
        history_store.append_observations(vault_path, indicator_id, [obs])

    return RegimeCollectResult(observations=observations, errors=errors)


def load_current_observations(vault_path: Path) -> dict[IndicatorId, IndicatorObservation]:
    """history JSONL에서 지표별 현재 알려진 최신값을 복원한다. `regime score`를 `regime
    collect`와 별도 프로세스/실행으로 돌릴 때(analyze가 collect와 분리되어 있는 것과 동일한
    패턴) 이걸로 입력을 재구성한다."""
    observations: dict[IndicatorId, IndicatorObservation] = {}
    for indicator_id in IndicatorId:
        obs = history_store.latest_observation(history_store.read_history(vault_path, indicator_id))
        if obs is not None:
            observations[indicator_id] = obs
    return observations


def _processed_path(vault_path: Path, as_of: date) -> Path:
    return vault_path / PROCESSED_DIR / f"{as_of.isoformat()}.json"


def load_snapshot(vault_path: Path, as_of: date) -> RegimeSnapshot | None:
    path = _processed_path(vault_path, as_of)
    if not path.exists():
        return None
    return RegimeSnapshot.model_validate_json(path.read_text(encoding="utf-8"))


def _write_processed(vault_path: Path, snapshot: RegimeSnapshot) -> Path:
    path = _processed_path(vault_path, snapshot.report.as_of)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    return path


def run_regime_score(
    vault_path: Path,
    observations: dict[IndicatorId, IndicatorObservation],
    as_of: date,
) -> DailyRegimeReport:
    """어제 저장된 processed 스냅샷(있다면)을 기준으로 신호 지속성/신규 발표를 판정하고,
    오늘의 원본 관측치까지 함께 processed/<date>.json에 저장한다(다음날 비교용)."""
    previous_snapshot = load_snapshot(vault_path, as_of - timedelta(days=1))
    previous_observations = previous_snapshot.observations if previous_snapshot else None

    scores = scoring.compute_scores(observations)
    market_regime = classify_market_regime(scores, observations)
    ai_regime = classify_ai_regime(scores, observations)
    signals = build_signals(observations, previous_observations)
    new_releases = report_renderer.detect_new_releases(observations, previous_observations)
    report = report_renderer.build_report(
        as_of, observations, signals, market_regime, ai_regime, scores, new_releases
    )

    _write_processed(vault_path, RegimeSnapshot(report=report, observations=observations))
    return report


def run_regime_report(
    vault_path: Path,
    report: DailyRegimeReport,
    observations: dict[IndicatorId, IndicatorObservation],
) -> Path:
    report_dir = vault_path / REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / f"{report.as_of.isoformat()}.md"
    json_path = report_dir / f"{report.as_of.isoformat()}.json"
    md_path.write_text(report_renderer.render_markdown(report, observations), encoding="utf-8")
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return md_path


@dataclass
class RegimeDailyResult:
    report: DailyRegimeReport | None = None
    report_path: str | None = None
    errors: list[str] = field(default_factory=list)


def run_regime_daily(vault_path: Path, settings: AppSettings) -> RegimeDailyResult:
    """collect -> score -> report 순서로 전체 파이프라인을 실행한다. LLM을 쓰지 않는다."""
    fetched_at = datetime.now(UTC)
    collect_result = run_regime_collect(vault_path, settings, fetched_at)
    report = run_regime_score(vault_path, collect_result.observations, fetched_at.date())
    report_path = run_regime_report(vault_path, report, collect_result.observations)
    return RegimeDailyResult(
        report=report, report_path=str(report_path), errors=collect_result.errors
    )

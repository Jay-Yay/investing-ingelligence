from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.config.settings import AppSettings
from investor_intel.llm.client import AnthropicClient
from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.market_data.yahoo_fundamentals_adapter import (
    BROWSER_LIKE_USER_AGENT,
    YahooFundamentalsAdapter,
)
from investor_intel.market_data.yfinance_adapter import YahooFinanceAdapter
from investor_intel.regime import history_store, report_renderer, scoring
from investor_intel.regime.ai_extraction import (
    HyperscalerAiRevenueExtraction,
    extract_ai_revenue_metrics,
)
from investor_intel.regime.collectors import (
    ai_hyperscaler_capex,
    ai_semiconductor_demand,
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
from investor_intel.storage.obsidian_repo import read_document
from investor_intel.storage.sqlite_index import connect, latest_filing_for_ticker

PROCESSED_DIR = "60_MarketRegime/processed"
REPORT_DIR = "50_Reports/MarketRegime"

_HYPERSCALER_AI_TICKERS = ("MSFT", "GOOGL", "AMZN", "META", "ORCL")
_SEMICONDUCTOR_AI_TICKERS = ("NVDA", "AVGO")
_SEC_FILING_TYPES = ("10-Q", "10-K")

_FRED_COLLECTORS = (credit_spread, anfci, yield_curve, employment)

# EPS 수정 폭은 무료 데이터 소스가 없어 "정상적으로" unavailable이다 - collect 오류 목록에
# 노이즈로 넣지 않는다 (unavailable_stub.py 참고).
_EXPECTED_UNAVAILABLE = {
    IndicatorId.EPS_REVISION_BREADTH,
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
    """무료 지표 9개(EPS 수정 폭 제외 전체)를 수집해
    vault/60_MarketRegime/history/<indicator_id>.jsonl에 append한다. LLM을 쓰지 않으므로
    무인 실행(GitHub Actions)이 가능하다 - cloud/AI 매출 등 LLM이 필요한 세부 필드는
    `regime analyze-ai`(Phase 2b, 수동)가 별도로 채운다."""
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

    # 하이퍼스케일러 CapEx/반도체 매출 지표(Phase 2a) - Yahoo Finance 분기 재무제표 기반,
    # LLM을 쓰지 않으므로 여기서도 무인 실행 가능하다. cloud/AI 세그먼트 매출 등 세부 필드는
    # `regime analyze-ai`(Phase 2b, 수동)가 나중에 채운다.
    fundamentals_client = SimpleHttpClient(user_agent=BROWSER_LIKE_USER_AGENT)
    try:
        fundamentals_adapter = YahooFundamentalsAdapter(fundamentals_client)
        obs = ai_hyperscaler_capex.collect(fundamentals_adapter, fetched_at)
        observations[obs.indicator_id] = obs
        obs = ai_semiconductor_demand.collect(fundamentals_adapter, fetched_at)
        observations[obs.indicator_id] = obs
    finally:
        fundamentals_client.close()

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


@dataclass
class RegimeAnalyzeAiResult:
    processed: int = 0
    errors: list[str] = field(default_factory=list)


def _extract_for_ticker(
    ticker: str,
    conn: sqlite3.Connection,
    vault_path: Path,
    client: AnthropicClient,
    cost_tracker: CostTracker,
    prompt: str,
) -> HyperscalerAiRevenueExtraction | None:
    row = latest_filing_for_ticker(conn, ticker, _SEC_FILING_TYPES)
    if row is None:
        return None
    doc_path = vault_path / row["file_path"]
    if not doc_path.exists():
        return None
    _, body = read_document(doc_path)
    outcome = extract_ai_revenue_metrics(client, body, prompt)
    cost_tracker.record_usage(
        client.model, outcome.usage.input_tokens, outcome.usage.output_tokens
    )
    return outcome.result


def _merge_hyperscaler_extractions(
    vault_path: Path, extractions: dict[str, HyperscalerAiRevenueExtraction]
) -> None:
    history = history_store.read_history(vault_path, IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY)
    latest = history_store.latest_observation(history)
    if latest is None:
        return

    details = dict(latest.details)
    companies = dict(details.get("companies") or {})
    for ticker, extraction in extractions.items():
        company = dict(companies.get(ticker) or {})
        company["cloud_or_ai_revenue"] = extraction.cloud_or_ai_revenue
        company["cloud_or_ai_revenue_unit"] = extraction.cloud_or_ai_revenue_unit
        company["cloud_ai_revenue_growth_yoy_pct"] = extraction.yoy_growth_pct
        company["reporting_period"] = extraction.reporting_period
        company["guidance_direction"] = extraction.guidance_direction.value
        company["guidance_quote"] = extraction.guidance_quote
        company["source_quote"] = extraction.source_quote
        companies[ticker] = company
    details["companies"] = companies

    growths = [
        c["cloud_ai_revenue_growth_yoy_pct"]
        for c in companies.values()
        if c.get("cloud_ai_revenue_growth_yoy_pct") is not None
    ]
    composite_growth = None if not growths else round(statistics.median(growths), 1)
    details["cloud_ai_revenue_growth_yoy"] = composite_growth

    # 스펙 원문의 monetization_gap = zscore(capex_growth_yoy) - zscore(cloud_ai_revenue_growth_yoy)
    # 는 두 시계열의 장기 분포가 있어야 z-score를 낼 수 있는데, 아직 그 정도 히스토리가
    # 쌓이지 않았다 - 우선 단순 차이(퍼센트포인트)로 근사한다. 두 성장률의 절대 스케일이
    # 다르면 왜곡될 수 있다는 한계를 details에 명시해 둔다.
    capex_growth = details.get("capex_growth_yoy")
    monetization_gap = (
        None
        if capex_growth is None or composite_growth is None
        else round(float(capex_growth) - float(composite_growth), 1)
    )
    details["monetization_gap"] = monetization_gap
    details["monetization_gap_note"] = (
        "z-score 기반 스펙 공식이 아니라 capex_growth_yoy - cloud_ai_revenue_growth_yoy "
        "단순 차이로 근사(장기 히스토리 부족)"
    )
    details["note"] = "cloud/AI 매출 관련 필드는 regime analyze-ai(LLM)로 채워졌다"

    updated = latest.model_copy(update={"details": details, "fetched_at": datetime.now(UTC)})
    history_store.append_observations(
        vault_path, IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY, [updated]
    )


def _merge_semiconductor_extractions(
    vault_path: Path, extractions: dict[str, HyperscalerAiRevenueExtraction]
) -> None:
    history = history_store.read_history(vault_path, IndicatorId.AI_SEMICONDUCTOR_DEMAND)
    latest = history_store.latest_observation(history)
    if latest is None:
        return

    details = dict(latest.details)
    companies = dict(details.get("companies") or {})
    for ticker, extraction in extractions.items():
        company = dict(companies.get(ticker) or {})
        company["datacenter_segment_revenue"] = extraction.cloud_or_ai_revenue
        company["datacenter_segment_revenue_unit"] = extraction.cloud_or_ai_revenue_unit
        company["datacenter_segment_revenue_growth_yoy_pct"] = extraction.yoy_growth_pct
        company["reporting_period"] = extraction.reporting_period
        company["guidance_direction"] = extraction.guidance_direction.value
        company["guidance_quote"] = extraction.guidance_quote
        company["source_quote"] = extraction.source_quote
        companies[ticker] = company
    details["companies"] = companies

    growths = [
        c["datacenter_segment_revenue_growth_yoy_pct"]
        for c in companies.values()
        if c.get("datacenter_segment_revenue_growth_yoy_pct") is not None
    ]
    details["datacenter_segment_revenue_growth_yoy"] = (
        None if not growths else round(statistics.median(growths), 1)
    )
    details["note"] = "NVIDIA/Broadcom 데이터센터 세그먼트 필드는 regime analyze-ai(LLM)로 채워졌다"

    updated = latest.model_copy(update={"details": details, "fetched_at": datetime.now(UTC)})
    history_store.append_observations(vault_path, IndicatorId.AI_SEMICONDUCTOR_DEMAND, [updated])


def run_regime_analyze_ai(
    vault_path: Path,
    sqlite_path: Path,
    client: AnthropicClient,
    cost_tracker: CostTracker,
    prompt: str,
) -> RegimeAnalyzeAiResult:
    """MSFT/GOOGL/AMZN/META/ORCL(하이퍼스케일러) + NVDA/AVGO(반도체 데이터센터 세그먼트)의
    최신 10-Q/10-K에서 클라우드/AI 매출 성장률과 CapEx 가이던스 방향을 LLM으로 추출해, 오늘
    이미 수집된 ai_hyperscaler_capex_efficiency/ai_semiconductor_demand 관측치의 details를
    보강한다.

    ANTHROPIC_API_KEY와 LLM 예산이 필요해 `regime collect`/`run-daily`와 분리된 수동 명령
    으로만 실행된다(무인 daily-collect.yml 크론에는 포함하지 않는다) - `collect` ->
    `analyze-ai` -> `score` -> `report` 순서로 실행해야 오늘 리포트에 반영된다. 대상 티커
    각각의 최신 10-Q/10-K가 vault에 이미 수집돼 있어야 한다(SEC 필링 자체는 이 함수가
    새로 수집하지 않는다 - 기존 `collect` 단계가 이미 담당).
    """
    result = RegimeAnalyzeAiResult()
    conn = connect(sqlite_path)
    try:
        hyperscaler_extractions: dict[str, HyperscalerAiRevenueExtraction] = {}
        for ticker in _HYPERSCALER_AI_TICKERS:
            if not cost_tracker.is_within_budget():
                result.errors.append("LLM 예산 초과 - 남은 하이퍼스케일러 종목 건너뜀")
                break
            try:
                extraction = _extract_for_ticker(
                    ticker, conn, vault_path, client, cost_tracker, prompt
                )
            except Exception as exc:  # noqa: BLE001 - 종목 하나 실패해도 나머지는 계속 진행
                result.errors.append(f"{ticker}: {exc}")
                continue
            if extraction is not None:
                hyperscaler_extractions[ticker] = extraction
                result.processed += 1

        semiconductor_extractions: dict[str, HyperscalerAiRevenueExtraction] = {}
        for ticker in _SEMICONDUCTOR_AI_TICKERS:
            if not cost_tracker.is_within_budget():
                result.errors.append("LLM 예산 초과 - 남은 반도체 종목 건너뜀")
                break
            try:
                extraction = _extract_for_ticker(
                    ticker, conn, vault_path, client, cost_tracker, prompt
                )
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"{ticker}: {exc}")
                continue
            if extraction is not None:
                semiconductor_extractions[ticker] = extraction
                result.processed += 1
    finally:
        conn.close()

    if hyperscaler_extractions:
        _merge_hyperscaler_extractions(vault_path, hyperscaler_extractions)
    if semiconductor_extractions:
        _merge_semiconductor_extractions(vault_path, semiconductor_extractions)

    return result

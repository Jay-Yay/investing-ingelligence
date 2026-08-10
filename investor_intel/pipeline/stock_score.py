from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.config.loaders import (
    load_global_scoring_yaml,
    load_scoring_universe_yaml,
    load_sector_scoring_yaml,
)
from investor_intel.llm.bear_case_critic import BearCaseCriticError
from investor_intel.llm.bear_case_critic import critique as run_bear_case_critique
from investor_intel.llm.client import AnthropicClient
from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.llm.evidence_collector import EvidenceCollectorError, extract_evidence
from investor_intel.llm.fundamental_analyst import FundamentalAnalystError, assess_fundamentals
from investor_intel.market_data.provider import PriceBar, QuarterlyFundamentals
from investor_intel.market_data.yahoo_fundamentals_adapter import (
    BROWSER_LIKE_USER_AGENT,
    YahooFundamentalsAdapter,
)
from investor_intel.market_data.yfinance_adapter import YahooFinanceAdapter
from investor_intel.models.analysis import FundamentalAnalystAssessment
from investor_intel.models.common import ThesisShift
from investor_intel.models.config import (
    HardGateDefinition,
    SectorScoringConfig,
)
from investor_intel.regime import history_store as regime_history_store
from investor_intel.regime import scoring as regime_scoring
from investor_intel.scoring.hysteresis import HysteresisState
from investor_intel.scoring.models import (
    Citation,
    DriverNote,
    Feature,
    SourceTier,
    StockScoreResult,
    ThesisStatus,
)
from investor_intel.scoring.pipeline import StockScoringInputs, compute_stock_score
from investor_intel.scoring.price_supply_demand import compute_price_supply_demand_metrics
from investor_intel.scoring.snapshot import (
    StockScoreSnapshot,
    compute_score_changes,
    load_latest_snapshot_before,
    load_previous_hysteresis,
    save_snapshot,
)
from investor_intel.storage.obsidian_repo import read_document, resolve_document_path

# 벤치마크 이름 -> Yahoo 심볼. KRX_SEMICONDUCTOR는 Yahoo에 깔끔한 무료 심볼이 없어 지원하지
# 않는다 - 이 경우 상대강도(rs_*_vs_benchmark)는 missing으로 남는다(README "알려진 한계").
_BENCHMARK_YAHOO_SYMBOLS = {
    "KOSPI": "^KS11",
    "SP500": "^GSPC",
    "NASDAQ100": "^NDX",
    "PHLX_SEMICONDUCTOR": "^SOX",
}

_PRICE_HISTORY_DAYS = 400


def _load_ticker_config(
    ticker: str, config_dir: Path
) -> tuple[str, dict[str, float], dict[str, list[str]], dict, list[HardGateDefinition]]:
    """(model_version, category_weights, metric_categories, metric_specs, hard_gate_definitions)."""
    universe = load_scoring_universe_yaml(config_dir / "scoring" / "universe.yaml")
    entry = next((t for t in universe.tickers if t.ticker == ticker), None)
    sector_name = entry.sector if entry else None

    global_config = load_global_scoring_yaml(config_dir / "scoring" / "global_scoring.yaml")
    sector_path = config_dir / "scoring" / f"sector_{sector_name}.yaml" if sector_name else None

    if sector_path is not None and sector_path.exists():
        sector: SectorScoringConfig = load_sector_scoring_yaml(sector_path)
        return (
            sector.model_version,
            sector.category_weights,
            sector.features,
            sector.metric_specs,
            list(global_config.hard_gates) + list(sector.extra_hard_gates),
        )
    return (
        global_config.model_version,
        global_config.category_weights,
        {},
        {},
        list(global_config.hard_gates),
    )


def _yoy_growth_pct(points: list, offset: int = 4) -> float | None:
    if len(points) <= offset:
        return None
    older = points[-1 - offset].value
    latest = points[-1].value
    if older == 0:
        return None
    return round((latest - older) / abs(older) * 100.0, 2)


def _fundamentals_to_features(
    ticker: str, fundamentals: QuarterlyFundamentals, retrieved_at: datetime
) -> list[Feature]:
    """Yahoo 분기 재무제표(실제 기업 공시 기반)에서 YoY 성장률 feature를 만든다. official
    tier/reported_fact로 취급한다 - 유료 컨센서스 데이터가 아니라 실제 파일링된 수치이기
    때문이다."""
    features: list[Feature] = []

    def _add(metric: str, points: list, unit: str = "pct_yoy") -> None:
        value = _yoy_growth_pct(points)
        if value is None:
            return
        latest_date = points[-1].as_of_date
        features.append(
            Feature(
                ticker=ticker,
                metric=metric,
                value=value,
                unit=unit,
                period=latest_date.isoformat(),
                published_at=datetime(
                    latest_date.year, latest_date.month, latest_date.day, tzinfo=UTC
                ),
                retrieved_at=retrieved_at,
                source_name="Yahoo Finance fundamentals-timeseries",
                source_url="https://query2.finance.yahoo.com/",
                source_tier=SourceTier.OFFICIAL,
                fact_type="reported_fact",  # type: ignore[arg-type]
                confidence=0.9,
                max_age_days=120,
            )
        )

    _add(
        "capex_growth",
        [p.model_copy(update={"value": abs(p.value)}) for p in fundamentals.capital_expenditure],
    )
    _add("operating_cash_flow_growth", fundamentals.operating_cash_flow)

    fcf_by_date = {
        p.as_of_date: p.value
        for p in fundamentals.operating_cash_flow
    }
    capex_by_date = {p.as_of_date: p.value for p in fundamentals.capital_expenditure}
    common_dates = sorted(set(fcf_by_date) & set(capex_by_date))
    if len(common_dates) > 4:
        fcf_points = [
            type(fundamentals.operating_cash_flow[0])(
                as_of_date=d, value=fcf_by_date[d] + capex_by_date[d]
            )
            for d in common_dates
        ]
        _add("free_cash_flow_growth", fcf_points)

    return features


def _resolve_benchmark_bars(
    yahoo: YahooFinanceAdapter, benchmarks: list[str]
) -> list[PriceBar]:
    for name in benchmarks:
        symbol = _BENCHMARK_YAHOO_SYMBOLS.get(name)
        if symbol is None:
            continue
        try:
            return yahoo.get_price_history(symbol, _PRICE_HISTORY_DAYS)
        except Exception:  # noqa: BLE001 - 벤치마크 하나 실패해도 다음 후보로 계속
            continue
    return []


@dataclass
class MacroLiquidity:
    score: float | None
    rationale: str
    citations: list[Citation]


def _macro_liquidity(vault_path: Path, as_of: date) -> MacroLiquidity:
    """regime 모듈의 cooling_risk를 "낙관적일수록 높은 점수" 방향으로 뒤집어 재사용한다 -
    시장 매크로 조건은 모든 종목이 공유하므로 종목마다 다시 계산하지 않는다."""
    observations = {}
    from investor_intel.regime.models import IndicatorId

    for indicator_id in IndicatorId:
        obs = regime_history_store.latest_observation(
            regime_history_store.read_history(vault_path, indicator_id)
        )
        if obs is not None:
            observations[indicator_id] = obs
    if not observations:
        return MacroLiquidity(score=None, rationale="", citations=[])
    scores = regime_scoring.compute_scores(observations)
    if scores.cooling_risk is None:
        return MacroLiquidity(score=None, rationale="", citations=[])
    rationale, citation_pairs = regime_scoring.build_cooling_risk_rationale(observations)
    citations = [Citation(label=label, url=url) for label, url in citation_pairs]
    return MacroLiquidity(
        score=round(100.0 - scores.cooling_risk, 1), rationale=rationale, citations=citations
    )


@dataclass
class StockScoreComputeResult:
    result: StockScoreResult
    hysteresis: HysteresisState
    snapshot_path: Path
    warnings: list[str] = field(default_factory=list)


def run_score_compute(
    ticker: str,
    vault_path: Path,
    config_dir: Path,
    as_of: date | None = None,
    currently_held: bool = False,
    extra_features: list[Feature] | None = None,
    positive_drivers: list[DriverNote] | None = None,
    negative_drivers: list[DriverNote] | None = None,
    next_catalysts: list[str] | None = None,
) -> StockScoreComputeResult:
    """섹션 17 daily 실행. LLM을 쓰지 않는다 - 가격/거래량/재무제표 성장률만 갱신하고, 밸류에이션
    가정과 EPS 수정치는 직전(주간) 스냅샷에서 그대로 이어받는다.

    `extra_features`는 `run_score_weekly`가 Evidence Collector로 뽑아낸 메모리 산업
    Feature(DRAM/HBM 가격 등)를 이번 계산에 함께 반영하기 위한 주입 지점이다 - 일간 단독
    실행(`score compute`)에서는 생략하면 되고, `score run-weekly`는 반드시 채워 넘긴다(그렇지
    않으면 Evidence Collector가 뽑은 근거가 점수에 전혀 반영되지 않는다).

    `positive_drivers`/`negative_drivers`/`next_catalysts`도 마찬가지로 `run_score_weekly`가
    Fundamental Analyst 출력을 넘기는 주입 지점이다 - None이면(daily 단독 실행) 직전 주간
    스냅샷 값을 그대로 이어받는다(valuation_scenarios/earnings_revision_inputs와 동일한
    "주간에만 갱신, 일간은 유지" 원칙)."""
    as_of = as_of or date.today()
    warnings: list[str] = []

    model_version, category_weights, metric_categories, metric_specs, hard_gates = (
        _load_ticker_config(ticker, config_dir)
    )
    universe = load_scoring_universe_yaml(config_dir / "scoring" / "universe.yaml")
    entry = next((t for t in universe.tickers if t.ticker == ticker), None)
    benchmarks = entry.benchmarks if entry else universe.default_benchmarks

    http = SimpleHttpClient()
    fundamentals_http = SimpleHttpClient(user_agent=BROWSER_LIKE_USER_AGENT)
    try:
        yahoo = YahooFinanceAdapter(http)
        bars = yahoo.get_price_history(ticker, _PRICE_HISTORY_DAYS)
        benchmark_bars = _resolve_benchmark_bars(yahoo, benchmarks)
        if not benchmark_bars:
            warnings.append(f"벤치마크 가격 히스토리 조회 실패/미지원 (benchmarks={benchmarks})")

        fundamentals_adapter = YahooFundamentalsAdapter(fundamentals_http)
        try:
            fundamentals = fundamentals_adapter.get_quarterly_fundamentals(ticker)
        except Exception as exc:  # noqa: BLE001 - 재무제표 조회 실패해도 가격 기반 점수는 계속 진행
            warnings.append(f"분기 재무제표 조회 실패({exc}) - 관련 feature는 missing 처리됨")
            fundamentals = QuarterlyFundamentals(symbol=ticker)
        current_price = bars[-1].close if bars else None
    finally:
        http.close()
        fundamentals_http.close()

    retrieved_at = datetime.now(UTC)
    features = _fundamentals_to_features(ticker, fundamentals, retrieved_at)
    features.extend(extra_features or [])
    price_metrics = compute_price_supply_demand_metrics(bars, benchmark_bars) if bars else None

    prior_snapshot = load_latest_snapshot_before(vault_path, ticker, as_of)
    valuation_scenarios = prior_snapshot.valuation_scenarios if prior_snapshot else None
    earnings_revision_inputs = prior_snapshot.earnings_revision_inputs if prior_snapshot else None
    if prior_snapshot is None:
        warnings.append("이전 주간 스냅샷 없음 - 밸류에이션/EPS 수정 카테고리는 missing 처리됨")

    if positive_drivers is None:
        positive_drivers = prior_snapshot.result.positive_drivers if prior_snapshot else []
    if negative_drivers is None:
        negative_drivers = prior_snapshot.result.negative_drivers if prior_snapshot else []
    if next_catalysts is None:
        next_catalysts = prior_snapshot.result.next_catalysts if prior_snapshot else []

    previous_hysteresis = load_previous_hysteresis(vault_path, ticker, as_of)
    days_since_last_change = (
        (as_of - previous_hysteresis.since).days
        if previous_hysteresis and previous_hysteresis.since
        else 999
    )

    score_1d, score_1w, score_1m = compute_score_changes(
        vault_path, ticker, as_of, None
    )  # placeholder - 실제 값은 total_score 계산 후 아래에서 다시 채운다

    macro_liquidity = _macro_liquidity(vault_path, as_of)
    inputs = StockScoringInputs(
        ticker=ticker,
        as_of=as_of,
        model_version=model_version,
        category_weights=category_weights,
        metric_categories=metric_categories,
        metric_specs=metric_specs,
        features=features,
        earnings_revision_inputs=earnings_revision_inputs,
        price_metrics=price_metrics,
        valuation_scenarios=valuation_scenarios,
        current_price=current_price,
        macro_liquidity_score=macro_liquidity.score,
        macro_liquidity_rationale=macro_liquidity.rationale,
        macro_liquidity_citations=macro_liquidity.citations,
        hard_gate_definitions=hard_gates,
        hysteresis_config=load_global_scoring_yaml(
            config_dir / "scoring" / "global_scoring.yaml"
        ).hysteresis,
        confidence_config=load_global_scoring_yaml(
            config_dir / "scoring" / "global_scoring.yaml"
        ).confidence,
        currently_held=currently_held,
        previous_hysteresis=previous_hysteresis,
        days_since_last_change=days_since_last_change,
        thesis_status=(
            prior_snapshot.result.thesis_status if prior_snapshot else ThesisStatus.MAINTAINED
        ),
        positive_drivers=positive_drivers,
        negative_drivers=negative_drivers,
        next_catalysts=next_catalysts,
    )
    result, hysteresis_state = compute_stock_score(inputs)

    score_1d, score_1w, score_1m = compute_score_changes(
        vault_path, ticker, as_of, result.total_score
    )
    result = result.model_copy(
        update={
            "score_change_1d": score_1d,
            "score_change_1w": score_1w,
            "score_change_1m": score_1m,
        }
    )

    snapshot = StockScoreSnapshot(
        result=result,
        hysteresis=hysteresis_state,
        valuation_scenarios=valuation_scenarios,
        earnings_revision_inputs=earnings_revision_inputs,
    )
    path = save_snapshot(vault_path, snapshot)
    return StockScoreComputeResult(
        result=result, hysteresis=hysteresis_state, snapshot_path=path, warnings=warnings
    )


def find_recent_documents_for_ticker(
    conn: sqlite3.Connection, vault_path: Path, ticker: str, since_days: int = 14
) -> list[tuple[str, str, datetime, str]]:
    """이 종목이 언급된 최근 문서를 찾는다.

    `document_assets`(=frontmatter `assets` 필드) 조인은 쓰지 않는다 - 그 테이블은 SEC 공시
    문서의 `assets`용으로 이미 쓰이고 있고(`sqlite_index.latest_filing_for_ticker`), 국내 IB
    리포트/DART 문서는 종목을 `assets`가 아니라 `companies` 프론트매터 필드에 담는다(SQLite
    컬럼으로 인덱싱돼 있지 않음). 대신 최근 기간 문서를 훑어 각 파일의 `companies` 필드를
    직접 확인한다 - 매일 수집량이 많지 않아 이 방식으로 충분하다.

    universe.yaml의 "005930.KS" 같은 표기는 DART 저장 시 쓰이는 6자리 코드("005930")와
    다르므로 거래소 접미사를 제거해서도 매칭한다. 반환: (source_name, source_url, published_at,
    body_text) 목록."""
    dart_code = ticker.split(".")[0]
    cutoff = (datetime.now(UTC) - timedelta(days=since_days)).isoformat()
    rows = conn.execute(
        "SELECT file_path FROM documents WHERE published_at >= ? ORDER BY published_at DESC",
        (cutoff,),
    ).fetchall()

    results: list[tuple[str, str, datetime, str]] = []
    for row in rows:
        path = resolve_document_path(vault_path, row["file_path"])
        if path is None:
            continue
        doc, body = read_document(path)
        if dart_code not in doc.companies and ticker not in doc.companies:
            continue
        results.append((doc.source_name, doc.source_url, doc.published_at, body))
    return results


@dataclass
class StockScoreWeeklyResult(StockScoreComputeResult):
    thesis_shift: ThesisShift | None = None
    documents_used: int = 0


def run_score_weekly(
    ticker: str,
    vault_path: Path,
    config_dir: Path,
    sqlite_conn: sqlite3.Connection,
    anthropic_client: AnthropicClient,
    cost_tracker: CostTracker,
    evidence_collector_prompt: str,
    fundamental_analyst_prompt: str,
    bear_case_critic_prompt: str,
    as_of: date | None = None,
    currently_held: bool = False,
    since_days: int = 14,
) -> StockScoreWeeklyResult:
    """섹션 17 weekly 실행. LLM 4역할 중 3개(Evidence Collector/Fundamental Analyst/Bear Case
    Critic)를 이 종목의 최근 문서에 대해 실행한다. Model Reviewer는 evaluation.py의 성과 요약이
    쌓인 뒤 별도 명령(`score review-model`)에서 실행한다 - 매주 돌릴 이유가 없는 역할이다.

    `cost_tracker`로 매 LLM 호출 전 예산을 확인하고(`analyze.py`와 동일한 패턴) 호출 후
    실제 토큰 사용량을 기록한다 - 문서 수만큼 Evidence Collector를 호출하므로 예산 확인 없이
    돌리면 하루 예산을 이 명령 하나가 다 써버릴 수 있다.

    이 함수가 만드는 밸류에이션 시나리오(bear/base/bull EPS×배수)는 아직 완전히 자동화하지
    않았다 - 사이클 국면 판단이 필요해 이번 구현 범위에서는 직전 스냅샷 값을 그대로 이어받는다
    (README "알려진 한계"에 명시). 원하면 CLI에서 새 시나리오를 수동으로 넘길 수 있다.
    """
    _, category_weights, metric_categories, metric_specs, _ = _load_ticker_config(
        ticker, config_dir
    )
    documents = find_recent_documents_for_ticker(sqlite_conn, vault_path, ticker, since_days)

    weekly_warnings: list[str] = []
    allowed_metrics = sorted({m for metrics in metric_categories.values() for m in metrics})
    extra_features: list[Feature] = []
    documents_used = 0
    for source_name, source_url, published_at, body in documents:
        if not allowed_metrics or not cost_tracker.is_within_budget():
            break
        try:
            outcome = extract_evidence(
                anthropic_client,
                ticker,
                source_name,
                source_url,
                published_at,
                body,
                evidence_collector_prompt,
                allowed_metrics,
            )
        except EvidenceCollectorError as exc:
            # 섹션 21 "LLM 응답 실패 시 안전한 Fallback" - 문서 하나의 추출이 반복 실패해도
            # (예: 모델이 배열 필드에 원본 텍스트를 잘못 채워 스키마 검증에 실패) 나머지
            # 문서·이후 단계는 계속 진행한다 - collect/analyze의 "부분 실패 허용" 원칙과 동일.
            weekly_warnings.append(f"{source_name} 근거 추출 실패, 건너뜀: {exc}")
            continue
        cost_tracker.record_usage(
            anthropic_client.model, outcome.usage.input_tokens, outcome.usage.output_tokens
        )
        extra_features.extend(outcome.features)
        documents_used += 1

    thesis_shift: ThesisShift | None = None
    fa_result: FundamentalAnalystAssessment | None = None
    if documents and cost_tracker.is_within_budget():
        evidence_context = "\n".join(
            f"- {f.metric}={f.value if f.value is not None else f.details.get('trend')} "
            f"({f.period}, {f.source_name}, {f.source_url})"
            for f in extra_features
        ) or "이번 주 새로운 구조화 근거 없음"
        try:
            fa_outcome = assess_fundamentals(
                anthropic_client, ticker, evidence_context, "", fundamental_analyst_prompt
            )
            cost_tracker.record_usage(
                anthropic_client.model,
                fa_outcome.usage.input_tokens,
                fa_outcome.usage.output_tokens,
            )
            thesis_shift = fa_outcome.result.thesis_shift
            fa_result = fa_outcome.result
            assess_context = (
                f"thesis_shift={fa_outcome.result.thesis_shift.value}\n"
                f"causal_chain={fa_outcome.result.causal_chain}"
            )
            if cost_tracker.is_within_budget():
                try:
                    bc_outcome = run_bear_case_critique(
                        anthropic_client,
                        ticker,
                        assess_context,
                        evidence_context,
                        bear_case_critic_prompt,
                    )
                    cost_tracker.record_usage(
                        anthropic_client.model,
                        bc_outcome.usage.input_tokens,
                        bc_outcome.usage.output_tokens,
                    )
                except BearCaseCriticError as exc:
                    weekly_warnings.append(f"Bear Case Critic 실패(점수는 정상 반영됨): {exc}")
        except FundamentalAnalystError as exc:
            weekly_warnings.append(
                f"Fundamental Analyst 실패, thesis_shift 갱신 안 됨(점수는 정상 반영됨): {exc}"
            )

    base_result = run_score_compute(
        ticker,
        vault_path,
        config_dir,
        as_of,
        currently_held,
        extra_features=extra_features,
        positive_drivers=fa_result.new_positive_drivers if fa_result else None,
        negative_drivers=fa_result.new_negative_drivers if fa_result else None,
        next_catalysts=fa_result.next_catalysts if fa_result else None,
    )
    base_result.warnings.extend(weekly_warnings)

    return StockScoreWeeklyResult(
        result=base_result.result,
        hysteresis=base_result.hysteresis,
        snapshot_path=base_result.snapshot_path,
        warnings=base_result.warnings,
        thesis_shift=thesis_shift,
        documents_used=documents_used,
    )

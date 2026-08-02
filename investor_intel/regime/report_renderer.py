from __future__ import annotations

from datetime import date

from investor_intel.regime.models import (
    AiRegime,
    DailyRegimeReport,
    DataQuality,
    IndicatorId,
    IndicatorObservation,
    IndicatorStatus,
    MarketRegime,
    RegimeSignal,
    ScoreBreakdown,
    SignalStatus,
)
from investor_intel.regime.scoring import ScoringResult

_MACRO_IDS = [
    IndicatorId.CREDIT_SPREAD_HY_OAS,
    IndicatorId.CHICAGO_FED_ANFCI,
    IndicatorId.EMPLOYMENT_COOLING,
    IndicatorId.YIELD_CURVE_10Y3M,
]
_EQUITY_IDS = [
    IndicatorId.EPS_REVISION_BREADTH,
    IndicatorId.MARKET_BREADTH,
    IndicatorId.VIX_TERM_STRUCTURE,
    IndicatorId.LEVERAGE_POSITIONING,
]
_AI_IDS = [
    IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY,
    IndicatorId.AI_SEMICONDUCTOR_DEMAND,
]


def _data_quality(observations: dict[IndicatorId, IndicatorObservation]) -> DataQuality:
    total = len(IndicatorId)
    stale = [
        obs.indicator_name
        for obs in observations.values()
        if obs.status == IndicatorStatus.OK and obs.is_stale
    ]
    unavailable = [
        obs.indicator_name
        for obs in observations.values()
        if obs.status in (IndicatorStatus.UNAVAILABLE, IndicatorStatus.ERROR)
    ]
    ok_count = sum(1 for obs in observations.values() if obs.status == IndicatorStatus.OK)
    coverage = round(ok_count / total, 3) if total else 0.0
    errors = [
        f"{obs.indicator_name}: {obs.details.get('error_reason')}"
        for obs in observations.values()
        if obs.status == IndicatorStatus.ERROR
    ]
    return DataQuality(
        coverage_ratio=coverage,
        stale_indicators=stale,
        unavailable_indicators=unavailable,
        errors=errors,
    )


def build_report(
    as_of: date,
    observations: dict[IndicatorId, IndicatorObservation],
    signals: list[RegimeSignal],
    market_regime: MarketRegime,
    ai_regime: AiRegime,
    scores: ScoringResult,
    new_releases: list[str],
) -> DailyRegimeReport:
    warnings = [
        f"{obs.indicator_name}: {obs.details.get('error_reason')}"
        for obs in observations.values()
        if obs.status == IndicatorStatus.UNAVAILABLE and obs.indicator_id not in (
            IndicatorId.EPS_REVISION_BREADTH,
            IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY,
            IndicatorId.AI_SEMICONDUCTOR_DEMAND,
        )
    ]
    if scores.ai_coverage == 0:
        warnings.append(
            "AI 산업 지표(하이퍼스케일러 Capex/AI 매출, 반도체 실수요)는 Phase 1에 미구현 - "
            "ai_cycle_score/ai_regime은 항상 indeterminate"
        )

    return DailyRegimeReport(
        as_of=as_of,
        market_regime=market_regime,
        ai_regime=ai_regime,
        scores=ScoreBreakdown(
            cooling_risk=scores.cooling_risk,
            overheating_risk=scores.overheating_risk,
            ai_cycle=scores.ai_cycle,
            data_confidence=scores.data_confidence,
        ),
        confidence_level=scores.confidence_level,
        signals=signals,
        new_releases=new_releases,
        warnings=warnings,
        data_quality=_data_quality(observations),
    )


def detect_new_releases(
    observations: dict[IndicatorId, IndicatorObservation],
    previous_observations: dict[IndicatorId, IndicatorObservation] | None,
) -> list[str]:
    previous_observations = previous_observations or {}
    releases: list[str] = []
    for indicator_id, obs in observations.items():
        if obs.status != IndicatorStatus.OK:
            continue
        prev = previous_observations.get(indicator_id)
        if prev is None or prev.observation_date != obs.observation_date or prev.value != obs.value:
            prev_value = "N/A" if prev is None or prev.value is None else prev.value
            releases.append(
                f"{obs.indicator_name}: {prev_value} -> {obs.value} "
                f"(기준일 {obs.observation_date.isoformat()})"
            )
    return releases


def _fmt(value: object) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _indicator_line(obs: IndicatorObservation) -> str:
    if obs.status != IndicatorStatus.OK:
        reason = obs.details.get("error_reason", "N/A")
        return f"- **{obs.indicator_name}**: unavailable ({reason})"
    age_note = " [stale]" if obs.is_stale else ""
    detail_parts = ", ".join(
        f"{k}={_fmt(v)}" for k, v in obs.details.items() if k != "instruments"
    )
    return (
        f"- **{obs.indicator_name}**: {_fmt(obs.value)} {obs.unit} "
        f"(기준일 {obs.observation_date.isoformat()}, 경과 {obs.data_age_days}일{age_note}) "
        f"- {detail_parts}"
    )


def _section_indicators(title: str, ids: list[IndicatorId], observations: dict) -> str:
    lines = [f"## {title}"]
    for indicator_id in ids:
        obs = observations.get(indicator_id)
        lines.append(_indicator_line(obs) if obs is not None else f"- **{indicator_id}**: N/A")
    return "\n".join(lines)


def render_markdown(
    report: DailyRegimeReport, observations: dict[IndicatorId, IndicatorObservation]
) -> str:
    lines: list[str] = ["# Daily Market Regime Report", ""]

    lines += [
        "## 1. 결론",
        f"- Market regime: {report.market_regime.value}",
        f"- AI regime: {report.ai_regime.value}",
        f"- Cooling risk score: {_fmt(report.scores.cooling_risk)}",
        f"- Overheating risk score: {_fmt(report.scores.overheating_risk)}",
        f"- AI cycle score: {_fmt(report.scores.ai_cycle)}",
        f"- Data confidence score: {_fmt(report.scores.data_confidence)}",
        f"- Confidence level: {report.confidence_level.value}",
        "",
        "## 2. 오늘 실제로 변경된 지표",
    ]
    lines += (
        [f"- {r}" for r in report.new_releases] if report.new_releases else ["신규 발표 없음"]
    )
    lines.append("")

    lines.append("## 3. 핵심 경고")
    new_warnings = [s for s in report.signals if s.status == SignalStatus.WATCH]
    maintained = [s for s in report.signals if s.status == SignalStatus.CONFIRMED]
    resolved = [s for s in report.signals if s.status == SignalStatus.RESOLVED]
    def _fmt_signal(s: RegimeSignal) -> str:
        return f"- {s.indicator_id.value}: {s.direction.value} (severity {s.severity}) - {s.reason}"

    lines.append("**신규/관찰(watch)**")
    lines += [_fmt_signal(s) for s in new_warnings] if new_warnings else ["없음"]
    lines.append("**유지 중(confirmed)**")
    lines += [_fmt_signal(s) for s in maintained] if maintained else ["없음"]
    lines.append("**해제됨(resolved)**")
    lines += [f"- {s.indicator_id.value}" for s in resolved] if resolved else ["없음"]
    lines.append("")

    lines.append(_section_indicators("4. 매크로", _MACRO_IDS, observations))
    lines.append("")
    lines.append(_section_indicators("5. 주식시장", _EQUITY_IDS, observations))
    lines.append("")
    lines.append(_section_indicators("6. AI 산업", _AI_IDS, observations))
    lines.append("")

    lines.append("## 7. 상충하는 신호")
    cooling = report.scores.cooling_risk or 0
    overheating = report.scores.overheating_risk or 0
    both_present = (
        report.scores.cooling_risk is not None and report.scores.overheating_risk is not None
    )
    if both_present and cooling >= 50 and overheating >= 50:
        lines.append(
            f"냉각 위험({cooling})과 과열 위험({overheating})이 동시에 중간 이상으로 나타남 - "
            "시장 가격/포지셔닝은 낙관적이나 신용·고용 등 펀더멘털은 악화되는 국면일 수 있다."
        )
    else:
        lines.append("뚜렷한 상충 신호 없음")
    lines.append("")

    lines.append("## 8. 데이터 품질")
    dq = report.data_quality
    unavailable_note = ", ".join(dq.unavailable_indicators) if dq.unavailable_indicators else "없음"
    stale_note = ", ".join(dq.stale_indicators) if dq.stale_indicators else "없음"
    errors_note = ", ".join(dq.errors) if dq.errors else "없음"
    lines.append(f"- 커버리지: {dq.coverage_ratio * 100:.0f}%")
    lines.append(f"- unavailable 지표: {unavailable_note}")
    lines.append(f"- stale 지표: {stale_note}")
    lines.append(f"- 수집 오류: {errors_note}")
    lines.append("- 추정값 사용 여부: 없음 (원칙상 데이터 없으면 unavailable로 처리)")
    for warning in report.warnings:
        lines.append(f"- {warning}")
    lines.append("")

    lines.append("## 9. 판단 근거")
    top_signals = sorted(
        [s for s in report.signals if s.status in (SignalStatus.WATCH, SignalStatus.CONFIRMED)],
        key=lambda s: s.severity,
        reverse=True,
    )[:5]
    if top_signals:
        for s in top_signals:
            obs = observations.get(s.indicator_id)
            value_note = "" if obs is None else f" (현재값 {_fmt(obs.value)} {obs.unit})"
            lines.append(f"- {s.indicator_id.value}{value_note}: {s.reason}")
    else:
        lines.append("판단을 바꾼 핵심 데이터 없음")

    return "\n".join(lines) + "\n"

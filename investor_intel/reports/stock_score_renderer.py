from __future__ import annotations

from investor_intel.scoring.hysteresis import HysteresisState
from investor_intel.scoring.models import CategoryScore, DriverNote, StockScoreResult
from investor_intel.scoring.valuation_scenarios import ValuationCase, ValuationScenarios


def _fmt(value: float | None, suffix: str = "") -> str:
    return "N/A" if value is None else f"{value:,.1f}{suffix}"


def _indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


def _render_category_score(cs: CategoryScore) -> list[str]:
    lines = [
        f"- {cs.category}: {_fmt(cs.score)} "
        f"(가중치 {cs.weight:.0f}, 커버리지 {cs.coverage:.0%}, "
        f"기여 feature {cs.contributing_features}개)"
    ]
    if cs.rationale:
        lines.append(_indent(cs.rationale))
    for citation in cs.citations:
        lines.append(_indent(f"- 출처: [{citation.label}]({citation.url})"))
    return lines


def _render_driver(d: DriverNote) -> list[str]:
    """CLAUDE.md의 "리서치 답변은 출처를 인라인 하이퍼링크로 표기" 규칙과 동일한 형식 -
    claim 자체를 링크 앵커 텍스트로 쓴다."""
    return [f"- **[{d.claim}]({d.source_url})**", _indent(d.rationale)]


def _fmt_case(case: ValuationCase | None, currency: str) -> str:
    if case is None:
        return "N/A"
    return (
        f"EPS {case.eps:,.0f}({case.eps_basis}) × {case.multiple:.1f}배 = "
        f"{case.fair_value:,.0f} {currency}\n  - 가정: {case.key_assumption}\n"
        f"  - 무효화 조건: {case.invalidation_condition}"
    )


def render_stock_score_report(
    result: StockScoreResult,
    hysteresis: HysteresisState,
    valuation_scenarios: ValuationScenarios | None,
    example_mode: bool = False,
) -> str:
    """섹션 20 12개 섹션 형식. `example_mode=True`면 맨 위에 "실시간 데이터 아님" 경고를
    붙인다 - README 예시 리포트용."""
    lines: list[str] = []
    header_note = " (Example - 일부 값은 실제 데이터가 아닐 수 있음)" if example_mode else ""
    lines.append(f"# {result.ticker} — {result.as_of.isoformat()}{header_note}")
    lines.append("")

    lines.append("## 1. 현재 판단")
    lines.append("")
    lines.append(f"- 총점: {_fmt(result.total_score)}")
    lines.append(f"- 전일 대비: {_fmt(result.score_change_1d)}")
    lines.append(f"- 1주 대비: {_fmt(result.score_change_1w)}")
    lines.append(f"- 1개월 대비: {_fmt(result.score_change_1m)}")
    lines.append(f"- 신뢰도: {result.confidence:.2f} ({result.confidence_level.value})")
    lines.append(f"- 현재 상태(신호): {result.signal.value if result.signal else 'N/A'}")
    lines.append(f"- 투자 가설 상태: {result.thesis_status.value}")
    triggered = [h for h in result.hard_gates if h.triggered]
    lines.append(
        "- 하드 게이트: " + (", ".join(h.gate_id for h in triggered) if triggered else "없음")
    )
    lines.append("")

    lines.append("## 2. 영역별 점수")
    lines.append("")
    for cs in result.category_scores:
        lines.extend(_render_category_score(cs))
    lines.append("")

    lines.append("## 3. 새롭게 확인된 사실")
    lines.append("")
    lines.append("(주간/이벤트 평가에서 Evidence Collector가 추출한 근거 - 출처/발표일 포함, "
                  "run-weekly 로그 참고)")
    lines.append("")

    lines.append("## 4. 이전 평가 대비 변경점")
    lines.append("")
    lines.append(
        f"- 점수 변화: 1일 {_fmt(result.score_change_1d)} / "
        f"1주 {_fmt(result.score_change_1w)} / 1개월 {_fmt(result.score_change_1m)}"
    )
    lines.append("")

    lines.append("## 5. 시장 기대 대비 평가")
    lines.append("")
    lines.append("(Fundamental Analyst의 consensus_comparison 판단 - run-weekly에서만 갱신됨)")
    lines.append("")

    lines.append("## 6. 긍정 요인")
    lines.append("")
    for d in result.positive_drivers:
        lines.extend(_render_driver(d))
    if not result.positive_drivers:
        lines.append("- 없음")
    lines.append("")

    lines.append("## 7. 부정 요인")
    lines.append("")
    for d in result.negative_drivers:
        lines.extend(_render_driver(d))
    if not result.negative_drivers:
        lines.append("- 없음")
    lines.append("")

    lines.append("## 8. 반대 논리")
    lines.append("")
    lines.append("(Bear Case Critic 출력 - run-weekly에서만 갱신됨)")
    lines.append("")

    lines.append("## 9. 시나리오")
    lines.append("")
    if valuation_scenarios is not None:
        currency = valuation_scenarios.currency
        lines.append(f"- 낙관(bull): {_fmt_case(valuation_scenarios.bull_case, currency)}")
        lines.append(f"- 기준(base): {_fmt_case(valuation_scenarios.base_case, currency)}")
        lines.append(f"- 비관(bear): {_fmt_case(valuation_scenarios.bear_case, currency)}")
    else:
        lines.append("- 밸류에이션 시나리오 없음 (run-weekly 실행 후 채워짐)")
    lines.append("")

    lines.append("## 10. 매매 판단")
    lines.append("")
    lines.append(f"- 신호: {result.signal.value if result.signal else 'N/A'} "
                  f"(신호 시작일: {hysteresis.since.isoformat() if hysteresis.since else 'N/A'})")
    lines.append("- 추가 매수/비중 축소/무효화 조건은 아래 §11 참고")
    lines.append("")

    lines.append("## 11. 다음 확인 지표")
    lines.append("")
    for c in result.next_catalysts:
        lines.append(f"- {c}")
    for c in result.invalidation_conditions:
        lines.append(f"- (무효화 조건) {c}")
    if not result.next_catalysts and not result.invalidation_conditions:
        lines.append("- 없음")
    lines.append("")

    lines.append("## 12. 데이터 품질")
    lines.append("")
    lines.append(f"- model_version: {result.model_version}")
    lines.append(
        f"- 누락된 핵심 데이터: {len(result.missing_critical_data)}건"
        + (
            f" (예: {', '.join(result.missing_critical_data[:5])} ...)"
            if result.missing_critical_data
            else ""
        )
    )
    lines.append("")

    return "\n".join(lines)

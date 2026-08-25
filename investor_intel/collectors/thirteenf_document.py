from __future__ import annotations

from investor_intel.collectors.thirteenf_changes import (
    concentration_ratio,
    position_count,
    top_holdings,
)
from investor_intel.models.config import InvestorConfig
from investor_intel.models.thirteenf import HoldingChange, ThirteenFFiling

THIRTEENF_LIMITATIONS_NOTE = (
    "- 13F은 분기 말 기준 스냅샷이며 제출까지 최대 45일의 시차가 존재한다.\n"
    "- 현재 실제 보유 상태와 다를 수 있다.\n"
    "- 공매도, 현금, 일부 파생상품 및 비공개 자산은 13F에 나타나지 않는다.\n"
    "- 종목이 사라졌다고 해서 반드시 부정적 전망을 의미하지 않는다.\n"
    "- put/call 정보가 있는 포지션은 보통주 보유와 혼합해서 해석하지 않는다.\n"
    "- 보고 가치만으로 투자자의 전체 순노출을 추정하지 않는다.\n"
)


def _render_holdings_table(changes: list[HoldingChange]) -> str:
    lines = [
        "| 종목 | CUSIP | 수량 | 보고가치($) | 비중 | 변화 | Put/Call | 원문행수 |",
        "| --- | --- | ---: | ---: | ---: | --- | --- | ---: |",
    ]
    for change in changes:
        weight = (
            f"{change.portfolio_weight_pct:.2f}%"
            if change.portfolio_weight_pct is not None
            else "-"
        )
        shares = (
            change.current_shares if change.current_shares is not None else change.previous_shares
        )
        value = (
            change.current_value_usd
            if change.current_value_usd is not None
            else change.previous_value_usd
        )
        lines.append(
            f"| {change.issuer} | {change.cusip} | {shares:,} "
            f"| {value:,} | {weight} | {change.change_type.value} "
            f"| {change.put_call or '-'} | {change.row_count} |"
        )
    return "\n".join(lines)


def render_thirteenf_body(
    filing: ThirteenFFiling,
    investor: InvestorConfig,
    changes: list[HoldingChange],
    canonical_url: str,
) -> str:
    top = top_holdings(filing.holdings, n=10)
    concentration = concentration_ratio(filing.holdings, top_n=5)

    new_count = sum(1 for c in changes if c.change_type.value == "new")
    sold_out_count = sum(1 for c in changes if c.change_type.value == "sold_out")

    sections = [
        "## 원문",
        "",
        f"{investor.fund_name} ({investor.name}) {filing.form_type} — "
        f"보고 기준일 {filing.period_of_report.isoformat()}, "
        f"제출일 {filing.filing_date.isoformat()}, "
        f"accession {filing.accession_number}",
        "",
        # 단위는 달러로 정규화돼 있다(2023-01-03 이후 제출본은 원문도 원 달러, 그 전은
        # 천 달러 단위라 파서가 1,000을 곱한다). "보유 포지션 수"는 합산된 포지션 수이고
        # 원문 행 수와 다른 것이 정상이므로 둘을 함께 적어 대조가 되게 한다.
        f"총 보고 가치: {filing.total_value_usd:,} 달러 / "
        f"보유 포지션 수: {position_count(filing.holdings)} "
        f"(원문 {len(filing.holdings)}행) / "
        f"상위 5종목 집중도: {concentration:.2f}%",
        "",
        _render_holdings_table(changes),
        "",
        "## 13F 해석 시 유의사항",
        "",
        THIRTEENF_LIMITATIONS_NOTE,
        "## 핵심 주장",
        "",
        "## 근거",
        "",
        "## 반대 근거",
        "",
        "## 언급 자산",
        "",
        f"신규 {new_count}종목, 전량 매도 {sold_out_count}종목. "
        f"상위 보유: {', '.join(h.issuer for h in top[:5])}",
        "",
        "## 포트폴리오 관련성",
        "",
        "## 출처",
        "",
        f"- [원문]({canonical_url})",
        "",
    ]
    return "\n".join(sections)

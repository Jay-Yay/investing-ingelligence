from __future__ import annotations

from pydantic import BaseModel


class ValuationCase(BaseModel):
    eps: float
    eps_basis: str  # "peak_earnings" | "current_forward_earnings" | "normalized_midcycle_earnings"
    multiple: float
    fair_value: float
    key_assumption: str
    invalidation_condition: str


class ValuationScenarios(BaseModel):
    """섹션 10. 단일 목표주가가 아니라 범위로 적정가치를 표현한다.

    peak_earnings/current_forward_earnings/normalized_midcycle_earnings 중 어느 것을
    bear/base/bull 각각에 대응시킬지는 지금 업황이 사이클의 어느 국면인지에 대한 판단이 필요해
    코드가 자동으로 정하지 않는다(호출부가 명시적으로 짝을 지어 넘긴다) - 예: 이익 정점 국면에서는
    peak_earnings에 낮은 배수를 곱한 값이 오히려 bear_case가 될 수 있다.
    """

    ticker: str
    currency: str
    bear_case: ValuationCase | None
    base_case: ValuationCase | None
    bull_case: ValuationCase | None


def build_case(
    eps: float | None,
    eps_basis: str,
    multiple: float | None,
    key_assumption: str,
    invalidation_condition: str,
) -> ValuationCase | None:
    if eps is None or multiple is None:
        return None
    return ValuationCase(
        eps=eps,
        eps_basis=eps_basis,
        multiple=multiple,
        fair_value=round(eps * multiple, 1),
        key_assumption=key_assumption,
        invalidation_condition=invalidation_condition,
    )


def valuation_score(
    current_price: float | None, scenarios: ValuationScenarios | None
) -> float | None:
    """현재가가 bear/base/bull 적정가치 범위 어디에 위치하는지를 0-100으로 변환한다
    (bear_case=100, base_case=50, bull_case=0 - 저평가일수록 높은 점수). base_case가 없으면
    계산 불가."""
    if current_price is None or scenarios is None or scenarios.base_case is None:
        return None
    base = scenarios.base_case.fair_value
    low = scenarios.bear_case.fair_value if scenarios.bear_case else base * 0.5
    high = scenarios.bull_case.fair_value if scenarios.bull_case else base * 1.5

    if current_price <= low:
        return 100.0
    if current_price >= high:
        return 0.0
    if current_price <= base:
        if base == low:
            return 75.0
        ratio = (base - current_price) / (base - low)
        return round(50.0 + ratio * 50.0, 1)
    if high == base:
        return 25.0
    ratio = (current_price - base) / (high - base)
    return round(50.0 - ratio * 50.0, 1)


def build_valuation_scenarios(
    ticker: str,
    currency: str,
    bear: ValuationCase | None,
    base: ValuationCase | None,
    bull: ValuationCase | None,
) -> ValuationScenarios:
    return ValuationScenarios(
        ticker=ticker, currency=currency, bear_case=bear, base_case=base, bull_case=bull
    )


def build_valuation_rationale(
    current_price: float | None, scenarios: ValuationScenarios | None
) -> str:
    """섹션 9 시나리오의 key_assumption을 근거로 현재가가 그 범위 어디에 있는지 설명한다.
    시나리오 자체가 (아직) 개별 출처 URL을 담지 않으므로 citation은 만들지 않는다 - 근거는
    섹션 9에서 시나리오 가정/무효화 조건으로 이미 노출된다."""
    if current_price is None or scenarios is None or scenarios.base_case is None:
        return ""
    base = scenarios.base_case
    lines = [
        f"- 현재가 {current_price:,.0f} {scenarios.currency} vs 기준(base) 적정가 "
        f"{base.fair_value:,.0f} {scenarios.currency}",
        f"- 기준 가정: {base.key_assumption}",
    ]
    if scenarios.bear_case is not None:
        lines.append(
            f"- 비관(bear) 적정가 {scenarios.bear_case.fair_value:,.0f} {scenarios.currency}"
        )
    if scenarios.bull_case is not None:
        lines.append(
            f"- 낙관(bull) 적정가 {scenarios.bull_case.fair_value:,.0f} {scenarios.currency}"
        )
    return "\n".join(lines[:5])

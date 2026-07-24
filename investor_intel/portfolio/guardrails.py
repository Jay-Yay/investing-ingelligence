from __future__ import annotations

from pydantic import BaseModel

from investor_intel.models.common import DecisionStatus, RecommendationRating
from investor_intel.models.portfolio import Portfolio
from investor_intel.portfolio.calculations import PositionMetrics, compute_sector_weights


class GuardrailViolation(BaseModel):
    symbol: str
    rule: str
    message: str


def check_guardrails(
    portfolio: Portfolio, metrics: list[PositionMetrics]
) -> list[GuardrailViolation]:
    violations: list[GuardrailViolation] = []
    constraints = portfolio.constraints

    for metric in metrics:
        if (
            metric.portfolio_weight is not None
            and metric.portfolio_weight > constraints.max_single_position_weight
        ):
            violations.append(
                GuardrailViolation(
                    symbol=metric.symbol,
                    rule="max_single_position_weight",
                    message=(
                        f"{metric.symbol} portfolio weight {metric.portfolio_weight:.2%} "
                        f"exceeds the {constraints.max_single_position_weight:.2%} limit"
                    ),
                )
            )

    sector_by_symbol = {position.symbol: position.sector for position in portfolio.positions}
    sector_weights = compute_sector_weights(portfolio.positions, metrics)
    for sector, weight in sector_weights.items():
        if weight > constraints.max_sector_weight:
            for symbol, sector_name in sector_by_symbol.items():
                if sector_name != sector:
                    continue
                violations.append(
                    GuardrailViolation(
                        symbol=symbol,
                        rule="max_sector_weight",
                        message=(
                            f"sector {sector} weight {weight:.2%} "
                            f"exceeds the {constraints.max_sector_weight:.2%} limit"
                        ),
                    )
                )

    for position in portfolio.positions:
        if not constraints.short_selling_allowed and position.quantity < 0:
            violations.append(
                GuardrailViolation(
                    symbol=position.symbol,
                    rule="short_selling_allowed",
                    message=(
                        f"{position.symbol} has a negative quantity (short position), "
                        "but short selling is not allowed"
                    ),
                )
            )
        if not constraints.options_allowed and "option" in position.asset_type.lower():
            violations.append(
                GuardrailViolation(
                    symbol=position.symbol,
                    rule="options_allowed",
                    message=(
                        f"{position.symbol} asset_type {position.asset_type!r} implies an "
                        "options position, but options are not allowed"
                    ),
                )
            )

    return violations


def decision_status_for(metrics: PositionMetrics) -> DecisionStatus:
    return DecisionStatus.PENDING if metrics.current_price is None else DecisionStatus.COMPLETE


def max_allowed_recommendation(
    violations: list[GuardrailViolation], symbol: str
) -> RecommendationRating | None:
    if any(violation.symbol == symbol for violation in violations):
        return RecommendationRating.HOLD
    return None

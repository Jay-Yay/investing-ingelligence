from __future__ import annotations

from pydantic import BaseModel

from investor_intel.models.portfolio import Position


class PositionMetrics(BaseModel):
    symbol: str
    current_price: float | None
    market_value: float | None
    cost_basis: float
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    portfolio_weight: float | None
    upside_to_target_pct: float | None


def compute_position_metrics(
    position: Position,
    current_price: float | None,
    total_market_value: float | None,
    fx_rate_to_base: float = 1.0,
) -> PositionMetrics:
    # market_value/cost_basis/unrealized_pnl are expressed in the portfolio's base_currency
    # (needed so portfolio_weight/sector weights sum correctly across mixed-currency
    # positions) - current_price stays in the position's own cost_currency since that's the
    # recognizable quote a user expects to see (e.g. an actual $187.77 for a US stock).
    cost_basis = position.quantity * position.average_cost * fx_rate_to_base

    if current_price is None:
        return PositionMetrics(
            symbol=position.symbol,
            current_price=None,
            market_value=None,
            cost_basis=cost_basis,
            unrealized_pnl=None,
            unrealized_pnl_pct=None,
            portfolio_weight=None,
            upside_to_target_pct=None,
        )

    market_value = position.quantity * current_price * fx_rate_to_base
    unrealized_pnl = market_value - cost_basis
    unrealized_pnl_pct = (unrealized_pnl / cost_basis * 100) if cost_basis else None
    portfolio_weight = (
        market_value / total_market_value if total_market_value else None
    )
    upside_to_target_pct = (
        (position.target_price - current_price) / current_price * 100
        if position.target_price is not None
        else None
    )

    return PositionMetrics(
        symbol=position.symbol,
        current_price=current_price,
        market_value=market_value,
        cost_basis=cost_basis,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        portfolio_weight=portfolio_weight,
        upside_to_target_pct=upside_to_target_pct,
    )


def compute_portfolio_metrics(
    positions: list[Position],
    prices: dict[str, float],
    fx_rates: dict[str, float] | None = None,
) -> list[PositionMetrics]:
    fx_rates = fx_rates or {}

    def rate_for(position: Position) -> float:
        return fx_rates.get(position.cost_currency, 1.0)

    total_market_value = sum(
        position.quantity * prices[position.symbol] * rate_for(position)
        for position in positions
        if position.symbol in prices
    )
    return [
        compute_position_metrics(
            position, prices.get(position.symbol), total_market_value, rate_for(position)
        )
        for position in positions
    ]


def compute_sector_weights(
    positions: list[Position], metrics: list[PositionMetrics]
) -> dict[str, float]:
    sector_by_symbol = {position.symbol: position.sector for position in positions}
    sector_totals: dict[str, float] = {}
    grand_total = 0.0

    for metric in metrics:
        if metric.market_value is None:
            continue
        sector = sector_by_symbol[metric.symbol]
        sector_totals[sector] = sector_totals.get(sector, 0.0) + metric.market_value
        grand_total += metric.market_value

    if grand_total == 0:
        return {}
    return {sector: total / grand_total for sector, total in sector_totals.items()}

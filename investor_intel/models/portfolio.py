from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class PortfolioConstraints(BaseModel):
    horizon_max_months: int
    max_single_position_weight: float
    max_sector_weight: float
    leverage_allowed: bool
    short_selling_allowed: bool
    options_allowed: bool


class Position(BaseModel):
    symbol: str
    name: str
    asset_type: str
    sector: str
    quantity: float
    average_cost: float
    cost_currency: str
    thesis: str = ""
    target_price: float | None = None
    stop_loss_price: float | None = None


class Portfolio(BaseModel):
    as_of: date
    base_currency: str
    constraints: PortfolioConstraints
    positions: list[Position]

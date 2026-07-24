from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from pydantic import BaseModel, field_validator


class Quote(BaseModel):
    symbol: str
    price: float
    currency: str
    as_of: datetime

    @field_validator("as_of")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        return value


class PriceBar(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketDataProvider(Protocol):
    def get_quote(self, symbol: str) -> Quote: ...

    def get_price_history(self, symbol: str, days: int) -> list[PriceBar]: ...

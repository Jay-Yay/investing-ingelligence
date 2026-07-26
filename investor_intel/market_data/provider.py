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


class FundamentalPoint(BaseModel):
    as_of_date: date
    value: float


class QuarterlyFundamentals(BaseModel):
    """분기 재무제표 시계열. 각 series는 오래된 분기 -> 최신 분기 순으로 정렬되어 있고,
    Yahoo가 해당 컨셉을 보고하지 않는 종목(외국민간발행인 등)은 빈 리스트가 된다."""

    symbol: str
    revenue: list[FundamentalPoint] = []
    operating_income: list[FundamentalPoint] = []
    net_income: list[FundamentalPoint] = []
    operating_cash_flow: list[FundamentalPoint] = []
    capital_expenditure: list[FundamentalPoint] = []  # Yahoo 원 부호(보통 유출은 음수) 그대로 보관
    cash_and_equivalents: list[FundamentalPoint] = []
    current_assets: list[FundamentalPoint] = []
    current_liabilities: list[FundamentalPoint] = []
    total_debt: list[FundamentalPoint] = []
    stockholders_equity: list[FundamentalPoint] = []

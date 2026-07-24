from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class VotingAuthority(BaseModel):
    sole: int
    shared: int
    none: int


class ThirteenFHolding(BaseModel):
    issuer: str
    title_of_class: str
    cusip: str
    figi: str | None = None
    value_usd_thousands: int
    shares_or_principal_amount: int
    shares_or_principal_type: str
    put_call: str | None = None
    investment_discretion: str
    other_manager: str | None = None
    voting_authority: VotingAuthority


class ThirteenFFiling(BaseModel):
    investor_id: str
    cik: str
    accession_number: str
    form_type: str
    filing_date: date
    period_of_report: date
    holdings: list[ThirteenFHolding]

    @property
    def total_value_usd_thousands(self) -> int:
        return sum(h.value_usd_thousands for h in self.holdings)


class HoldingChangeType(StrEnum):
    NEW = "new"
    SOLD_OUT = "sold_out"
    INCREASED = "increased"
    DECREASED = "decreased"
    HELD = "held"


class HoldingChange(BaseModel):
    cusip: str
    issuer: str
    change_type: HoldingChangeType
    previous_shares: int | None = None
    current_shares: int | None = None
    shares_change_pct: float | None = None
    previous_value_usd_thousands: int | None = None
    current_value_usd_thousands: int | None = None
    value_change_usd_thousands: int | None = None
    portfolio_weight_pct: float | None = None
    put_call: str | None = None

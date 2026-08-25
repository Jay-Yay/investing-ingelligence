from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class VotingAuthority(BaseModel):
    sole: int
    shared: int
    none: int


class ThirteenFHolding(BaseModel):
    """13F 정보표(informationTable)의 한 행.

    한 종목이 여러 행으로 나뉘어 보고되는 것이 정상이다(운용 재량 구분, 공동 운용사,
    put/call 별로 행이 갈린다). 따라서 행 수와 보유 종목 수는 같지 않다 - 포지션 단위로
    보려면 `thirteenf_changes.aggregate_positions`를 거쳐야 한다.

    `value_usd`는 **달러 단위로 정규화된 값**이다. 원문의 `<value>` 태그가 담는 단위는
    제출 시점에 따라 다르다(`thirteenf_parser.value_unit_for_filing_date` 참고).
    """

    issuer: str
    title_of_class: str
    cusip: str
    figi: str | None = None
    value_usd: int
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
    def total_value_usd(self) -> int:
        return sum(h.value_usd for h in self.holdings)


class HoldingChangeType(StrEnum):
    NEW = "new"
    SOLD_OUT = "sold_out"
    INCREASED = "increased"
    DECREASED = "decreased"
    HELD = "held"


class HoldingChange(BaseModel):
    """포지션 하나의 분기 대비 변화.

    `row_count`는 이 포지션이 원문에서 몇 개 행으로 보고됐는지다. 1이 아니면 여러 행을
    합산한 결과이므로, 원문 표와 대조할 때 행이 "사라진" 것처럼 보이지 않게 하려면 이
    숫자를 함께 보여줘야 한다.
    """

    cusip: str
    issuer: str
    change_type: HoldingChangeType
    previous_shares: int | None = None
    current_shares: int | None = None
    shares_change_pct: float | None = None
    previous_value_usd: int | None = None
    current_value_usd: int | None = None
    value_change_usd: int | None = None
    portfolio_weight_pct: float | None = None
    put_call: str | None = None
    row_count: int = 1

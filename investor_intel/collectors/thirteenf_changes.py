from __future__ import annotations

from investor_intel.models.thirteenf import (
    HoldingChange,
    HoldingChangeType,
    ThirteenFHolding,
    VotingAuthority,
)

# 포지션 하나를 식별하는 키. CUSIP만으로 묶으면 보통주와 put/call 포지션이 한 덩어리가 되는데,
# 13F 유의사항이 "put/call 정보가 있는 포지션은 보통주 보유와 혼합해서 해석하지 않는다"고
# 명시한 그대로 이 둘은 서로 다른 포지션이다.
_PositionKey = tuple[str, str | None]


def _key(holding: ThirteenFHolding) -> _PositionKey:
    return (holding.cusip, holding.put_call)


def aggregate_positions(
    holdings: list[ThirteenFHolding],
) -> dict[_PositionKey, tuple[ThirteenFHolding, int]]:
    """정보표의 여러 행을 포지션 단위로 합산한다.

    13F는 같은 종목을 운용 재량 구분·공동 운용사·put/call별로 **여러 행으로 나눠** 보고한다.
    예전 구현은 `{h.cusip: h for h in holdings}`로 묶어서 마지막 행만 남기고 나머지를 조용히
    덮어썼다. 실측(2024-11-14 필링)에서 121개 행이 37개 종목이었고, 그렇게 만들어진 표의
    비중 합계는 21.42%인데 같은 문서 머리글의 상위 5종목 집중도는 46.49%로 서로 모순이었다.
    한 매니저 슬라이스만 보고 "최대 비중 종목"을 답하게 되므로 반드시 합산해야 한다.

    돌려주는 값은 `키 -> (합산된 행, 원문 행 수)`다. 행 수를 함께 넘기는 이유는 원문 표와
    대조할 때 행이 사라진 것처럼 보이지 않게 하기 위해서다.
    """
    merged: dict[_PositionKey, tuple[ThirteenFHolding, int]] = {}
    for holding in holdings:
        key = _key(holding)
        existing = merged.get(key)
        if existing is None:
            merged[key] = (holding, 1)
            continue
        base, count = existing
        merged[key] = (
            base.model_copy(
                update={
                    "value_usd": base.value_usd + holding.value_usd,
                    "shares_or_principal_amount": (
                        base.shares_or_principal_amount + holding.shares_or_principal_amount
                    ),
                    "voting_authority": VotingAuthority(
                        sole=base.voting_authority.sole + holding.voting_authority.sole,
                        shared=base.voting_authority.shared + holding.voting_authority.shared,
                        none=base.voting_authority.none + holding.voting_authority.none,
                    ),
                    # 행마다 다를 수 있는 필드는 합산 결과를 특정 행에 귀속시키지 않는다.
                    "investment_discretion": (
                        base.investment_discretion
                        if base.investment_discretion == holding.investment_discretion
                        else "MULTIPLE"
                    ),
                    "other_manager": (
                        base.other_manager
                        if base.other_manager == holding.other_manager
                        else None
                    ),
                }
            ),
            count + 1,
        )
    return merged


def position_count(holdings: list[ThirteenFHolding]) -> int:
    """행 수가 아닌 포지션 수. 머리글의 '보유 종목 수'가 써야 하는 값이다."""
    return len(aggregate_positions(holdings))


def compute_holding_changes(
    previous_holdings: list[ThirteenFHolding] | None,
    current_holdings: list[ThirteenFHolding],
) -> list[HoldingChange]:
    previous_by_key = aggregate_positions(previous_holdings or [])
    current_by_key = aggregate_positions(current_holdings)
    current_total = sum(h.value_usd for h, _ in current_by_key.values()) or 1

    changes: list[HoldingChange] = []

    for key, (current, row_count) in current_by_key.items():
        cusip, put_call = key
        previous_entry = previous_by_key.get(key)
        portfolio_weight = round(current.value_usd / current_total * 100, 2)

        if previous_entry is None:
            changes.append(
                HoldingChange(
                    cusip=cusip,
                    issuer=current.issuer,
                    change_type=HoldingChangeType.NEW,
                    current_shares=current.shares_or_principal_amount,
                    current_value_usd=current.value_usd,
                    portfolio_weight_pct=portfolio_weight,
                    put_call=put_call,
                    row_count=row_count,
                )
            )
            continue

        previous = previous_entry[0]
        shares_change_pct = None
        if previous.shares_or_principal_amount != 0:
            shares_change_pct = round(
                (current.shares_or_principal_amount - previous.shares_or_principal_amount)
                / previous.shares_or_principal_amount
                * 100,
                2,
            )

        if current.shares_or_principal_amount > previous.shares_or_principal_amount:
            change_type = HoldingChangeType.INCREASED
        elif current.shares_or_principal_amount < previous.shares_or_principal_amount:
            change_type = HoldingChangeType.DECREASED
        else:
            change_type = HoldingChangeType.HELD

        changes.append(
            HoldingChange(
                cusip=cusip,
                issuer=current.issuer,
                change_type=change_type,
                previous_shares=previous.shares_or_principal_amount,
                current_shares=current.shares_or_principal_amount,
                shares_change_pct=shares_change_pct,
                previous_value_usd=previous.value_usd,
                current_value_usd=current.value_usd,
                value_change_usd=current.value_usd - previous.value_usd,
                portfolio_weight_pct=portfolio_weight,
                put_call=put_call,
                row_count=row_count,
            )
        )

    for key, (previous, row_count) in previous_by_key.items():
        if key in current_by_key:
            continue
        cusip, put_call = key
        changes.append(
            HoldingChange(
                cusip=cusip,
                issuer=previous.issuer,
                change_type=HoldingChangeType.SOLD_OUT,
                previous_shares=previous.shares_or_principal_amount,
                previous_value_usd=previous.value_usd,
                put_call=put_call,
                row_count=row_count,
            )
        )

    return changes


def top_holdings(holdings: list[ThirteenFHolding], n: int = 10) -> list[ThirteenFHolding]:
    """상위 보유 포지션. 행이 아니라 합산된 포지션 기준이다."""
    positions = [h for h, _ in aggregate_positions(holdings).values()]
    return sorted(positions, key=lambda h: h.value_usd, reverse=True)[:n]


def distinct_issuers(holdings: list[ThirteenFHolding]) -> list[str]:
    """보고 가치 순으로 정렬한 중복 없는 종목명.

    frontmatter의 `companies`에 행을 그대로 넣으면 같은 종목이 행 수만큼 반복된다(실측:
    121개 행 = 37개 종목). 그 중복이 지식 레이어의 관계 수까지 그대로 부풀렸다.
    """
    ordered = top_holdings(holdings, n=len(holdings))
    return list(dict.fromkeys(h.issuer for h in ordered))


def concentration_ratio(holdings: list[ThirteenFHolding], top_n: int = 5) -> float:
    total = sum(h.value_usd for h in holdings)
    if total == 0:
        return 0.0
    top_total = sum(h.value_usd for h in top_holdings(holdings, top_n))
    return round(top_total / total * 100, 2)

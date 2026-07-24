from __future__ import annotations

from investor_intel.models.thirteenf import HoldingChange, HoldingChangeType, ThirteenFHolding


def compute_holding_changes(
    previous_holdings: list[ThirteenFHolding] | None,
    current_holdings: list[ThirteenFHolding],
) -> list[HoldingChange]:
    previous_by_cusip = {h.cusip: h for h in (previous_holdings or [])}
    current_by_cusip = {h.cusip: h for h in current_holdings}
    current_total = sum(h.value_usd_thousands for h in current_holdings) or 1

    changes: list[HoldingChange] = []

    for cusip, current in current_by_cusip.items():
        previous = previous_by_cusip.get(cusip)
        portfolio_weight = round(current.value_usd_thousands / current_total * 100, 2)

        if previous is None:
            changes.append(
                HoldingChange(
                    cusip=cusip,
                    issuer=current.issuer,
                    change_type=HoldingChangeType.NEW,
                    current_shares=current.shares_or_principal_amount,
                    current_value_usd_thousands=current.value_usd_thousands,
                    portfolio_weight_pct=portfolio_weight,
                    put_call=current.put_call,
                )
            )
            continue

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
                previous_value_usd_thousands=previous.value_usd_thousands,
                current_value_usd_thousands=current.value_usd_thousands,
                value_change_usd_thousands=(
                    current.value_usd_thousands - previous.value_usd_thousands
                ),
                portfolio_weight_pct=portfolio_weight,
                put_call=current.put_call,
            )
        )

    for cusip, previous in previous_by_cusip.items():
        if cusip in current_by_cusip:
            continue
        changes.append(
            HoldingChange(
                cusip=cusip,
                issuer=previous.issuer,
                change_type=HoldingChangeType.SOLD_OUT,
                previous_shares=previous.shares_or_principal_amount,
                previous_value_usd_thousands=previous.value_usd_thousands,
                put_call=previous.put_call,
            )
        )

    return changes


def top_holdings(holdings: list[ThirteenFHolding], n: int = 10) -> list[ThirteenFHolding]:
    return sorted(holdings, key=lambda h: h.value_usd_thousands, reverse=True)[:n]


def concentration_ratio(holdings: list[ThirteenFHolding], top_n: int = 5) -> float:
    total = sum(h.value_usd_thousands for h in holdings)
    if total == 0:
        return 0.0
    top_total = sum(h.value_usd_thousands for h in top_holdings(holdings, top_n))
    return round(top_total / total * 100, 2)

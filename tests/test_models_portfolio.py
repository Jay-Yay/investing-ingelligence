from datetime import date

from investor_intel.models.portfolio import Portfolio, PortfolioConstraints, Position


def _constraints() -> PortfolioConstraints:
    return PortfolioConstraints(
        horizon_max_months=6,
        max_single_position_weight=0.60,
        max_sector_weight=0.60,
        leverage_allowed=False,
        short_selling_allowed=False,
        options_allowed=False,
    )


def test_position_defaults() -> None:
    position = Position(
        symbol="NBIS",
        name="Nebius Group",
        asset_type="us_equity",
        sector="AI Infrastructure",
        quantity=0,
        average_cost=0,
        cost_currency="USD",
    )
    assert position.thesis == ""
    assert position.target_price is None
    assert position.stop_loss_price is None


def test_portfolio_valid_construction() -> None:
    portfolio = Portfolio(
        as_of=date(2026, 7, 24),
        base_currency="KRW",
        constraints=_constraints(),
        positions=[
            Position(
                symbol="NBIS",
                name="Nebius Group",
                asset_type="us_equity",
                sector="AI Infrastructure",
                quantity=10,
                average_cost=40.0,
                cost_currency="USD",
            )
        ],
    )
    assert portfolio.base_currency == "KRW"
    assert len(portfolio.positions) == 1

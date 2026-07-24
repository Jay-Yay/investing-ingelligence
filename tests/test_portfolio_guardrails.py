from datetime import date

from investor_intel.models.common import DecisionStatus, RecommendationRating
from investor_intel.models.portfolio import Portfolio, PortfolioConstraints, Position
from investor_intel.portfolio.calculations import compute_portfolio_metrics
from investor_intel.portfolio.guardrails import (
    check_guardrails,
    decision_status_for,
    max_allowed_recommendation,
)


def _constraints(**overrides) -> PortfolioConstraints:
    defaults = dict(
        horizon_max_months=6,
        max_single_position_weight=0.60,
        max_sector_weight=0.60,
        leverage_allowed=False,
        short_selling_allowed=False,
        options_allowed=False,
    )
    defaults.update(overrides)
    return PortfolioConstraints(**defaults)


def _position(**overrides) -> Position:
    defaults = dict(
        symbol="NBIS",
        name="Nebius Group",
        asset_type="us_equity",
        sector="AI Infrastructure",
        quantity=10,
        average_cost=40.0,
        cost_currency="USD",
    )
    defaults.update(overrides)
    return Position(**defaults)


def _portfolio(positions, **constraint_overrides) -> Portfolio:
    return Portfolio(
        as_of=date(2026, 7, 24),
        base_currency="KRW",
        constraints=_constraints(**constraint_overrides),
        positions=positions,
    )


def test_flags_position_over_single_weight_limit() -> None:
    positions = [
        _position(symbol="NBIS", quantity=100, average_cost=40.0),
        _position(symbol="BE", quantity=1, average_cost=20.0, sector="Energy"),
    ]
    prices = {"NBIS": 50.0, "BE": 30.0}
    metrics = compute_portfolio_metrics(positions, prices)
    portfolio = _portfolio(positions, max_single_position_weight=0.60)

    violations = check_guardrails(portfolio, metrics)
    assert any(v.symbol == "NBIS" and v.rule == "max_single_position_weight" for v in violations)


def test_flags_sector_over_limit() -> None:
    positions = [
        _position(symbol="NBIS", quantity=10, average_cost=40.0, sector="AI Infrastructure"),
        _position(symbol="RDDT", quantity=10, average_cost=40.0, sector="AI Infrastructure"),
        _position(symbol="BE", quantity=1, average_cost=20.0, sector="Energy"),
    ]
    prices = {"NBIS": 50.0, "RDDT": 50.0, "BE": 30.0}
    metrics = compute_portfolio_metrics(positions, prices)
    portfolio = _portfolio(positions, max_sector_weight=0.60)

    violations = check_guardrails(portfolio, metrics)
    assert any(v.rule == "max_sector_weight" for v in violations)


def test_flags_short_position_when_not_allowed() -> None:
    positions = [_position(quantity=-10)]
    metrics = compute_portfolio_metrics(positions, {"NBIS": 50.0})
    portfolio = _portfolio(positions, short_selling_allowed=False)

    violations = check_guardrails(portfolio, metrics)
    assert any(v.rule == "short_selling_allowed" for v in violations)


def test_does_not_flag_short_position_when_allowed() -> None:
    positions = [_position(quantity=-10)]
    metrics = compute_portfolio_metrics(positions, {"NBIS": 50.0})
    portfolio = _portfolio(positions, short_selling_allowed=True)

    violations = check_guardrails(portfolio, metrics)
    assert not any(v.rule == "short_selling_allowed" for v in violations)


def test_flags_options_position_when_not_allowed() -> None:
    positions = [_position(asset_type="us_option")]
    metrics = compute_portfolio_metrics(positions, {"NBIS": 50.0})
    portfolio = _portfolio(positions, options_allowed=False)

    violations = check_guardrails(portfolio, metrics)
    assert any(v.rule == "options_allowed" for v in violations)


def test_clean_portfolio_has_no_violations() -> None:
    positions = [
        _position(symbol="NBIS", quantity=1, average_cost=40.0),
        _position(symbol="BE", quantity=2, average_cost=20.0, sector="Energy"),
    ]
    metrics = compute_portfolio_metrics(positions, {"NBIS": 50.0, "BE": 30.0})
    portfolio = _portfolio(positions)

    assert check_guardrails(portfolio, metrics) == []


def test_decision_status_pending_when_price_missing() -> None:
    positions = [_position()]
    metrics = compute_portfolio_metrics(positions, {})
    assert decision_status_for(metrics[0]) == DecisionStatus.PENDING


def test_decision_status_complete_when_price_present() -> None:
    positions = [_position()]
    metrics = compute_portfolio_metrics(positions, {"NBIS": 50.0})
    assert decision_status_for(metrics[0]) == DecisionStatus.COMPLETE


def test_max_allowed_recommendation_caps_violating_symbol() -> None:
    positions = [_position(symbol="NBIS", quantity=100, average_cost=40.0)]
    metrics = compute_portfolio_metrics(positions, {"NBIS": 50.0})
    portfolio = _portfolio(positions, max_single_position_weight=0.10)

    violations = check_guardrails(portfolio, metrics)
    assert max_allowed_recommendation(violations, "NBIS") == RecommendationRating.HOLD


def test_max_allowed_recommendation_none_for_clean_symbol() -> None:
    violations = []
    assert max_allowed_recommendation(violations, "NBIS") is None

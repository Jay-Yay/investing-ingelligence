import pytest

from investor_intel.models.portfolio import Position
from investor_intel.portfolio.calculations import (
    compute_portfolio_metrics,
    compute_position_metrics,
    compute_sector_weights,
)


def _position(**overrides) -> Position:
    defaults = dict(
        symbol="NBIS",
        name="Nebius Group",
        asset_type="us_equity",
        sector="AI Infrastructure",
        quantity=10,
        average_cost=40.0,
        cost_currency="USD",
        target_price=60.0,
    )
    defaults.update(overrides)
    return Position(**defaults)


def test_compute_position_metrics_pnl_arithmetic() -> None:
    metrics = compute_position_metrics(_position(), current_price=50.0, total_market_value=500.0)
    assert metrics.market_value == 500.0
    assert metrics.cost_basis == 400.0
    assert metrics.unrealized_pnl == 100.0
    assert metrics.unrealized_pnl_pct == pytest.approx(25.0)
    assert metrics.portfolio_weight == pytest.approx(1.0)
    assert metrics.upside_to_target_pct == pytest.approx(20.0)


def test_compute_position_metrics_zero_cost_basis_guarded() -> None:
    metrics = compute_position_metrics(
        _position(quantity=10, average_cost=0.0), current_price=50.0, total_market_value=500.0
    )
    assert metrics.cost_basis == 0.0
    assert metrics.unrealized_pnl_pct is None


def test_compute_position_metrics_missing_price_is_none() -> None:
    metrics = compute_position_metrics(_position(), current_price=None, total_market_value=None)
    assert metrics.current_price is None
    assert metrics.market_value is None
    assert metrics.unrealized_pnl is None
    assert metrics.unrealized_pnl_pct is None
    assert metrics.portfolio_weight is None
    assert metrics.upside_to_target_pct is None
    assert metrics.cost_basis == 400.0


def test_compute_position_metrics_no_target_price() -> None:
    metrics = compute_position_metrics(
        _position(target_price=None), current_price=50.0, total_market_value=500.0
    )
    assert metrics.upside_to_target_pct is None


def test_compute_portfolio_metrics_weights_sum_to_one() -> None:
    positions = [
        _position(symbol="NBIS", quantity=10, average_cost=40.0),
        _position(symbol="BE", quantity=5, average_cost=20.0, sector="Energy"),
    ]
    prices = {"NBIS": 50.0, "BE": 30.0}
    metrics = compute_portfolio_metrics(positions, prices)

    total_weight = sum(m.portfolio_weight for m in metrics if m.portfolio_weight is not None)
    assert total_weight == pytest.approx(1.0)


def test_compute_portfolio_metrics_missing_symbol_price() -> None:
    positions = [_position(symbol="NBIS")]
    metrics = compute_portfolio_metrics(positions, prices={})
    assert metrics[0].current_price is None


def test_compute_position_metrics_applies_fx_rate_to_market_value_and_cost_basis() -> None:
    metrics = compute_position_metrics(
        _position(quantity=10, average_cost=40.0, cost_currency="USD"),
        current_price=50.0,
        total_market_value=730_000.0,
        fx_rate_to_base=1460.0,
    )

    # current_price stays in native currency - only market_value/cost_basis (and anything
    # derived from them) convert into the portfolio's base currency
    assert metrics.current_price == 50.0
    assert metrics.market_value == pytest.approx(10 * 50.0 * 1460.0)
    assert metrics.cost_basis == pytest.approx(10 * 40.0 * 1460.0)
    assert metrics.portfolio_weight == pytest.approx((10 * 50.0 * 1460.0) / 730_000.0)


def test_compute_portfolio_metrics_mixed_currency_weights_sum_to_one() -> None:
    usd_position = _position(symbol="NBIS", quantity=10, average_cost=40.0, cost_currency="USD")
    krw_position = _position(
        symbol="005930", quantity=1, average_cost=250_000.0, cost_currency="KRW", sector="Tech"
    )
    prices = {"NBIS": 50.0, "005930": 260_000.0}

    metrics = compute_portfolio_metrics(
        [usd_position, krw_position], prices, fx_rates={"USD": 1460.0, "KRW": 1.0}
    )

    total_weight = sum(m.portfolio_weight for m in metrics if m.portfolio_weight is not None)
    assert total_weight == pytest.approx(1.0)

    nbis_metric = next(m for m in metrics if m.symbol == "NBIS")
    samsung_metric = next(m for m in metrics if m.symbol == "005930")
    # NBIS: 10 * 50 * 1460 = 730,000 KRW-equivalent; Samsung: 1 * 260,000 = 260,000 KRW
    assert nbis_metric.portfolio_weight == pytest.approx(730_000 / (730_000 + 260_000))
    assert samsung_metric.portfolio_weight == pytest.approx(260_000 / (730_000 + 260_000))


def test_compute_portfolio_metrics_unlisted_currency_falls_back_to_one_to_one() -> None:
    # no fx_rates passed at all - matches pre-multi-currency behavior for a single-currency
    # portfolio, and is the safe fallback when an fx lookup couldn't be completed
    positions = [_position(symbol="NBIS", quantity=10, average_cost=40.0)]
    metrics = compute_portfolio_metrics(positions, prices={"NBIS": 50.0})
    assert metrics[0].market_value == 500.0


def test_compute_sector_weights_aggregates_by_sector() -> None:
    positions = [
        _position(symbol="NBIS", quantity=10, average_cost=40.0, sector="AI Infrastructure"),
        _position(symbol="BE", quantity=5, average_cost=20.0, sector="Energy"),
        _position(symbol="RDDT", quantity=5, average_cost=20.0, sector="AI Infrastructure"),
    ]
    prices = {"NBIS": 50.0, "BE": 30.0, "RDDT": 50.0}
    metrics = compute_portfolio_metrics(positions, prices)
    sector_weights = compute_sector_weights(positions, metrics)

    # NBIS 500 + RDDT 250 = 750 AI Infra; BE 150 Energy; total 900
    assert sector_weights["AI Infrastructure"] == pytest.approx(750 / 900)
    assert sector_weights["Energy"] == pytest.approx(150 / 900)

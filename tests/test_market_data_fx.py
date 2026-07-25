from datetime import UTC, datetime

import pytest

from investor_intel.market_data.fx import build_fx_rates, fx_rate
from investor_intel.market_data.provider import Quote


class _FakeProvider:
    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def get_quote(self, symbol: str):
        if symbol not in self._prices:
            raise ValueError(f"no quote for {symbol}")
        return Quote(
            symbol=symbol,
            price=self._prices[symbol],
            currency=symbol,
            as_of=datetime(2026, 7, 26, tzinfo=UTC),
        )

    def get_price_history(self, symbol: str, days: int):
        raise NotImplementedError


def test_fx_rate_same_currency_is_one() -> None:
    provider = _FakeProvider({})
    assert fx_rate("USD", "USD", provider) == 1.0


def test_fx_rate_usd_to_krw_uses_direct_yahoo_quote() -> None:
    # Yahoo's "KRW=X" symbol already means "units of KRW per 1 USD"
    provider = _FakeProvider({"KRW=X": 1460.0})
    assert fx_rate("USD", "KRW", provider) == pytest.approx(1460.0)


def test_fx_rate_krw_to_usd_is_the_inverse() -> None:
    provider = _FakeProvider({"KRW=X": 1460.0})
    assert fx_rate("KRW", "USD", provider) == pytest.approx(1 / 1460.0)


def test_fx_rate_cross_pair_pivots_through_usd() -> None:
    provider = _FakeProvider({"KRW=X": 1460.0, "EUR=X": 0.9})
    # 1 EUR = 1/0.9 USD = (1/0.9)*1460 KRW
    expected = (1 / 0.9) * 1460.0
    assert fx_rate("EUR", "KRW", provider) == pytest.approx(expected)


def test_build_fx_rates_includes_base_currency_as_one() -> None:
    provider = _FakeProvider({"KRW=X": 1460.0})
    rates = build_fx_rates({"USD", "KRW"}, "KRW", provider)
    assert rates == {"USD": pytest.approx(1460.0), "KRW": 1.0}


def test_build_fx_rates_omits_currency_when_lookup_fails() -> None:
    provider = _FakeProvider({})  # no quotes available at all
    rates = build_fx_rates({"USD", "KRW"}, "KRW", provider)
    assert rates == {"KRW": 1.0}

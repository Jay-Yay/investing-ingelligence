from __future__ import annotations

from investor_intel.market_data.provider import MarketDataProvider

_YAHOO_FX_SYMBOL = "{currency}=X"


def _usd_per_unit(currency: str, provider: MarketDataProvider) -> float:
    """1 unit of `currency` expressed in USD. Yahoo Finance quotes FX pairs as "<CCY>=X" =
    units of <CCY> per 1 USD, so USD itself needs no lookup and no other pair is quotable."""
    if currency == "USD":
        return 1.0
    quote = provider.get_quote(_YAHOO_FX_SYMBOL.format(currency=currency))
    return 1.0 / quote.price


def fx_rate(from_currency: str, to_currency: str, provider: MarketDataProvider) -> float:
    """Multiplier that converts an amount in `from_currency` into `to_currency`."""
    if from_currency == to_currency:
        return 1.0
    from_usd = _usd_per_unit(from_currency, provider)
    to_usd = _usd_per_unit(to_currency, provider)
    return from_usd / to_usd


def build_fx_rates(
    currencies: set[str], base_currency: str, provider: MarketDataProvider
) -> dict[str, float]:
    """Best-effort: a currency whose rate lookup fails is simply omitted, so callers that
    fall back to a 1.0 multiplier for missing entries degrade gracefully instead of raising."""
    rates: dict[str, float] = {}
    for currency in currencies:
        if currency == base_currency:
            rates[currency] = 1.0
            continue
        try:
            rates[currency] = fx_rate(currency, base_currency, provider)
        except Exception:  # noqa: BLE001
            continue
    return rates

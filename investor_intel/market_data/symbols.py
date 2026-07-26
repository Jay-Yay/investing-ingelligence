from __future__ import annotations


def is_kr_stock_code(symbol: str) -> bool:
    """6-digit numeric codes (e.g. 005930) are KRX tickers - Yahoo Finance requires a market
    suffix (.KS for KOSPI, .KQ for KOSDAQ) that config/dart_companies.yaml doesn't track."""
    return symbol.isdigit() and len(symbol) == 6


def yahoo_symbol_candidates(symbol: str) -> list[str]:
    # KOSPI (.KS) is tried before KOSDAQ (.KQ): both can return *some* result for the same
    # 6-digit code since Yahoo doesn't reject a listing just because it belongs to the other
    # exchange, so this can't reliably detect a genuinely KOSDAQ-only ticker being served
    # KOSPI data for an unrelated instrument - .KS is preferred because it resolves every
    # KR ticker currently tracked in this project correctly.
    if is_kr_stock_code(symbol):
        return [f"{symbol}.KS", f"{symbol}.KQ"]
    return [symbol]

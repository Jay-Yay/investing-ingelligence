from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.market_data.provider import PriceBar
from investor_intel.market_data.yfinance_adapter import YahooFinanceAdapter
from investor_intel.regime.collectors.common import build_observation, unavailable_observation
from investor_intel.regime.models import IndicatorFrequency, IndicatorId, IndicatorObservation

# iShares IVV 보유종목 CSV 엔드포인트를 원래 계획했으나, 라이브 조회 결과 봇 차단(HTML
# 인터스티셜을 반환)으로 접근이 불가능함을 확인했다 - Runbook.md가 이미 문서화한 Morgan
# Stanley/State Street와 동일한 사례. 대신 위키피디아 S&P500 구성종목 표(무료, 봇 차단 없음,
# 라이브 검증됨)를 대체 소스로 쓴다.
_WIKIPEDIA_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
INDICATOR_NAME = "시장 폭(Market Breadth)"
SOURCE_NAME = "Wikipedia S&P 500 constituents + Yahoo Finance"
# 위키피디아 표는 티커를 "BRK.B"처럼 점 표기로 싣지만 Yahoo Finance는 "BRK-B"(하이픈)를 쓴다.
_TICKER_PATTERN = re.compile(r"^[A-Z0-9.\-]{1,10}$")


class _WikipediaConstituentsTableParser(HTMLParser):
    """위키피디아 `id="constituents"` 표를 행(셀 텍스트 리스트)의 나열로 파싱한다.

    이 표는 rowspan/colspan이 없는 단순 그리드임을 라이브 조회로 확인했다 - 그래서
    `table_markdown._TableParser`(rowspan/colspan 지원, DART/SEC 재무제표용)까지는 필요
    없고, 이 목적에 맞는 최소 파서를 별도로 둔다.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_table = False
        self._table_depth = 0
        self._current_row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            if dict(attrs).get("id") == "constituents":
                self._in_table = True
                self._table_depth = 1
            elif self._in_table:
                self._table_depth += 1
            return
        if not self._in_table:
            return
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table:
            self._table_depth -= 1
            if self._table_depth == 0:
                self._in_table = False
            return
        if not self._in_table:
            return
        if tag in ("td", "th") and self._cell_parts is not None:
            text = " ".join("".join(self._cell_parts).split())
            if self._current_row is not None:
                self._current_row.append(text)
            self._cell_parts = None
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)


def fetch_constituents(client: SimpleHttpClient) -> list[str]:
    """위키피디아 "List of S&P 500 companies" 표에서 Yahoo Finance 호환 티커 목록을 추출한다.

    포맷이 바뀌어 표/헤더를 못 찾으면 예외를 던지고, 호출부가 unavailable로 전환한다(임의로
    빈 목록을 반환하지 않는다).
    """
    text = client.get_text(_WIKIPEDIA_SP500_URL)
    parser = _WikipediaConstituentsTableParser()
    parser.feed(text)
    parser.close()

    if not parser.rows:
        raise ValueError("Wikipedia constituents table not found (format may have changed)")

    header = [c.strip() for c in parser.rows[0]]
    if "Symbol" not in header:
        raise ValueError("Symbol column not found in constituents table")
    symbol_col = header.index("Symbol")

    tickers: list[str] = []
    for row in parser.rows[1:]:
        if len(row) <= symbol_col:
            continue
        ticker = row[symbol_col].strip().replace(".", "-")
        if _TICKER_PATTERN.match(ticker):
            tickers.append(ticker)
    return tickers


def _above_moving_average(bars: list[PriceBar], window: int) -> bool | None:
    closes = [b.close for b in bars]
    if len(closes) < window:
        return None
    return closes[-1] > (sum(closes[-window:]) / window)


def _is_new_extreme(bars: list[PriceBar], window: int, want_high: bool) -> bool | None:
    closes = [b.close for b in bars]
    if len(closes) < window:
        return None
    extreme = max(closes[-window:]) if want_high else min(closes[-window:])
    return closes[-1] >= extreme if want_high else closes[-1] <= extreme


def _relative_return(bars_a: list[PriceBar], bars_b: list[PriceBar], n: int) -> float | None:
    if len(bars_a) <= n or len(bars_b) <= n:
        return None
    ratio_now = bars_a[-1].close / bars_b[-1].close
    ratio_then = bars_a[-1 - n].close / bars_b[-1 - n].close
    if ratio_then == 0:
        return None
    return round((ratio_now / ratio_then - 1) * 100, 2)


def _rsp_spy_relative_return(yahoo: YahooFinanceAdapter) -> tuple[float | None, float | None]:
    try:
        rsp_bars = yahoo.get_price_history("RSP", days=120)
        spy_bars = yahoo.get_price_history("SPY", days=120)
    except Exception:  # noqa: BLE001
        return None, None
    return (
        _relative_return(rsp_bars, spy_bars, 20),
        _relative_return(rsp_bars, spy_bars, 63),
    )


def collect(
    yahoo: YahooFinanceAdapter,
    constituents_client: SimpleHttpClient,
    fetched_at: datetime,
    max_constituents: int | None = None,
) -> IndicatorObservation:
    """value = S&P500 구성종목 중 200일 이동평균 위 종목 비율(%) - 스코어링 표에서
    "200일선 위 종목 비율 40% 미만"이 냉각 신호 기준선으로 명시된 헤드라인 숫자라 대표값으로
    쓴다. 나머지(50일선, 신고가/신저가, RSP/SPY 상대수익률)는 details에 담는다.

    개별 종목 하나의 가격 조회 실패는(상장폐지/티커 변경 등으로 500개 중 일부는 항상 있을 수
    있음) 전체 지표를 실패시키지 않고 표본에서 제외한다.
    """
    try:
        tickers = fetch_constituents(constituents_client)
    except Exception as exc:  # noqa: BLE001
        return unavailable(fetched_at, f"constituents fetch failed: {exc}")

    if max_constituents is not None:
        tickers = tickers[:max_constituents]
    if not tickers:
        return unavailable(fetched_at, "no constituents parsed from constituents table")

    above_50 = above_200 = new_highs = new_lows = sampled = 0
    for ticker in tickers:
        try:
            bars = yahoo.get_price_history(ticker, days=400)
        except Exception:  # noqa: BLE001
            continue
        if len(bars) < 50:
            continue
        sampled += 1
        if _above_moving_average(bars, 50):
            above_50 += 1
        if _above_moving_average(bars, 200):
            above_200 += 1
        if _is_new_extreme(bars, 252, want_high=True):
            new_highs += 1
        if _is_new_extreme(bars, 252, want_high=False):
            new_lows += 1

    if sampled == 0:
        return unavailable(fetched_at, "no constituent price history could be fetched")

    pct_above_50 = round(100 * above_50 / sampled, 1)
    pct_above_200 = round(100 * above_200 / sampled, 1)
    rsp_spy_20d, rsp_spy_63d = _rsp_spy_relative_return(yahoo)

    cooling_signal = bool(pct_above_200 < 40)
    narrow_leadership_signal = bool(rsp_spy_63d is not None and rsp_spy_63d < 0)

    return build_observation(
        indicator_id=IndicatorId.MARKET_BREADTH,
        indicator_name=INDICATOR_NAME,
        value=pct_above_200,
        unit="pct_above_200dma",
        observation_date=fetched_at.date(),
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=_WIKIPEDIA_SP500_URL,
        frequency=IndicatorFrequency.DAILY,
        details={
            "sample_size": sampled,
            "constituent_count": len(tickers),
            "pct_above_50dma": pct_above_50,
            "pct_above_200dma": pct_above_200,
            "new_highs_252d": new_highs,
            "new_lows_252d": new_lows,
            "new_high_low_ratio": None if new_lows == 0 else round(new_highs / new_lows, 2),
            "rsp_spy_return_20d_pct": rsp_spy_20d,
            "rsp_spy_return_63d_pct": rsp_spy_63d,
            "cooling_signal": cooling_signal,
            "narrow_leadership_signal": narrow_leadership_signal,
        },
    )


def unavailable(fetched_at: datetime, reason: str) -> IndicatorObservation:
    return unavailable_observation(
        indicator_id=IndicatorId.MARKET_BREADTH,
        indicator_name=INDICATOR_NAME,
        unit="pct_above_200dma",
        frequency=IndicatorFrequency.DAILY,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=_WIKIPEDIA_SP500_URL,
        reason=reason,
    )

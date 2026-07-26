from __future__ import annotations

import time
from datetime import date
from typing import Any

import httpx

from investor_intel.collectors.http_client import HttpClientError, SimpleHttpClient
from investor_intel.market_data.provider import FundamentalPoint, QuarterlyFundamentals
from investor_intel.market_data.symbols import yahoo_symbol_candidates

_CRUMB_COOKIE_URL = "https://fc.yahoo.com"
_CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
_TIMESERIES_URL = "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}"
_QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"

# 이 모듈이 쓰는 crumb/quoteSummary/fundamentals-timeseries 엔드포인트는 SimpleHttpClient의
# 기본 User-Agent("Investor Intel/0.1")를 봇으로 판단해 getcrumb에서 429를 반환한다 - 반면
# chart API(YahooFinanceAdapter)는 같은 UA로도 정상 동작한다. 실제 브라우저 UA를 흉내내면
# 통과하므로, 이 어댑터를 생성할 때는 아래 UA를 쓰는 SimpleHttpClient를 넘겨야 한다.
BROWSER_LIKE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 내부 필드명 -> Yahoo fundamentals-timeseries concept 접미사. 실제 요청 시 "quarterly"를 붙인다
# (예: quarterlyTotalRevenue). Yahoo가 20-F/6-K 발행사(외국민간발행인) 등 일부 종목에는 특정
# concept를 아예 보고하지 않을 수 있고, 그 경우 해당 필드는 빈 리스트로 남는다.
_CONCEPTS = {
    "revenue": "TotalRevenue",
    "operating_income": "OperatingIncome",
    "net_income": "NetIncome",
    "operating_cash_flow": "OperatingCashFlow",
    "capital_expenditure": "CapitalExpenditure",
    "cash_and_equivalents": "CashAndCashEquivalents",
    "current_assets": "CurrentAssets",
    "current_liabilities": "CurrentLiabilities",
    "total_debt": "TotalDebt",
    "stockholders_equity": "StockholdersEquity",
}


class YahooFundamentalsError(Exception):
    pass


class YahooFundamentalsAdapter:
    """분기 재무제표(fundamentals-timeseries)와 시가총액(quoteSummary)을 조회한다.

    quote/price-history 전용 chart API(YahooFinanceAdapter)와 달리 이 두 엔드포인트는 Yahoo의
    crumb+cookie 인증이 필요한 비공식 API다 - 세션당 한 번만 크럼을 발급받아 재사용한다.
    Yahoo가 예고 없이 형식을 바꿀 수 있으므로 실패 시 원인을 그대로 노출한다(조용히 넘어가지
    않는다).
    """

    def __init__(self, client: SimpleHttpClient) -> None:
        self._client = client
        self._crumb: str | None = None

    def _ensure_crumb(self) -> str:
        if self._crumb is not None:
            return self._crumb
        try:
            self._client.get(_CRUMB_COOKIE_URL)
        except (HttpClientError, httpx.HTTPStatusError):
            pass  # 쿠키만 필요 - 이 엔드포인트 자체의 응답 코드는 무관하다
        crumb = self._client.get_text(_CRUMB_URL).strip()
        if not crumb or crumb.startswith("<"):
            raise YahooFundamentalsError("Yahoo Finance crumb 발급 실패")
        self._crumb = crumb
        return crumb

    def get_market_cap(self, symbol: str) -> tuple[float, str]:
        """(market_cap, currency)를 반환한다. 6자리 한국 종목코드는 .KS/.KQ를 순서대로 시도한다."""
        crumb = self._ensure_crumb()
        last_error: Exception | None = None
        for candidate in yahoo_symbol_candidates(symbol):
            url = f"{_QUOTE_SUMMARY_URL.format(symbol=candidate)}?modules=price&crumb={crumb}"
            try:
                data = self._client.get_json(url)
            except (HttpClientError, httpx.HTTPStatusError) as exc:
                # 이 후보 심볼/거래소 접미사가 실패했을 뿐이니 다음 후보로 넘어간다 - 응답 파싱
                # 중 발생하는 오류(스키마 변경 등 실제 버그)는 여기서 잡지 않고 그대로 전파한다.
                last_error = exc
                continue
            results = data.get("quoteSummary", {}).get("result") or []
            if not results:
                last_error = YahooFundamentalsError(f"{candidate}: quoteSummary 결과 없음")
                continue
            price = results[0].get("price") or {}
            market_cap = price.get("marketCap", {}).get("raw")
            currency = price.get("currency")
            if market_cap is None or currency is None:
                last_error = YahooFundamentalsError(f"{candidate}: marketCap/currency 필드 없음")
                continue
            return float(market_cap), str(currency)
        assert last_error is not None
        raise last_error

    def get_quarterly_fundamentals(
        self, symbol: str, lookback_days: int = 3 * 365
    ) -> QuarterlyFundamentals:
        """6자리 한국 종목코드는 .KS/.KQ를 순서대로 시도하되, 반환되는 symbol 필드는 입력값을
        그대로 보존한다(포트폴리오 매칭 등 호출부가 거래소 접미사를 몰라도 되게 하기 위함)."""
        crumb = self._ensure_crumb()
        now = int(time.time())
        period1 = now - lookback_days * 24 * 3600
        types = ",".join(f"quarterly{suffix}" for suffix in _CONCEPTS.values())

        last_error: Exception | None = None
        for candidate in yahoo_symbol_candidates(symbol):
            url = (
                f"{_TIMESERIES_URL.format(symbol=candidate)}?symbol={candidate}&type={types}"
                f"&period1={period1}&period2={now}&crumb={crumb}"
            )
            try:
                data = self._client.get_json(url)
            except (HttpClientError, httpx.HTTPStatusError) as exc:
                last_error = exc
                continue
            timeseries = data.get("timeseries", {})
            if timeseries.get("error"):
                last_error = YahooFundamentalsError(f"{candidate}: {timeseries['error']}")
                continue
            results = timeseries.get("result") or []
            if not any(entry.get(_concept_type(entry)) for entry in results):
                last_error = YahooFundamentalsError(f"{candidate}: 재무제표 데이터 없음")
                continue
            return QuarterlyFundamentals(symbol=symbol, **_parse_series(results))
        assert last_error is not None
        raise last_error


def _concept_type(entry: dict[str, Any]) -> str:
    return str(entry["meta"]["type"][0])


def _parse_series(results: list[dict[str, Any]]) -> dict[str, list[FundamentalPoint]]:
    field_by_concept = {f"quarterly{suffix}": field for field, suffix in _CONCEPTS.items()}
    series: dict[str, list[FundamentalPoint]] = {}
    for entry in results:
        concept_type = _concept_type(entry)
        field_name = field_by_concept.get(concept_type)
        if field_name is None:
            continue
        points = [
            FundamentalPoint(
                as_of_date=date.fromisoformat(p["asOfDate"]),
                value=float(p["reportedValue"]["raw"]),
            )
            for p in entry.get(concept_type) or []
            if p and p.get("reportedValue") is not None
        ]
        series[field_name] = sorted(points, key=lambda pt: pt.as_of_date)
    return series

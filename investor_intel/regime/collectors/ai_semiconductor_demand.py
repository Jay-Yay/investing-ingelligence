from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime

from investor_intel.market_data.provider import QuarterlyFundamentals
from investor_intel.market_data.yahoo_fundamentals_adapter import YahooFundamentalsAdapter
from investor_intel.regime.collectors.common import (
    build_observation,
    ttm_series,
    unavailable_observation,
    yoy_growth_series,
)
from investor_intel.regime.models import IndicatorFrequency, IndicatorId, IndicatorObservation
from investor_intel.regime.percentile import percentile_rank

_TICKERS = ["TSM", "NVDA", "AVGO", "MU"]
INDICATOR_NAME = "AI 반도체 실수요"
SOURCE_NAME = "Yahoo Finance 분기 재무제표 (매출)"
_SOURCE_URL = "https://finance.yahoo.com/"
_LOOKBACK_DAYS = 5 * 365


@dataclass
class _CompanyMetrics:
    as_of: date
    revenue_growth_yoy_pct: float
    revenue_growth_yoy_5y_percentile: float | None


def _company_metrics(fundamentals: QuarterlyFundamentals) -> _CompanyMetrics | None:
    revenue_ttm = ttm_series(fundamentals.revenue)
    growth_series = yoy_growth_series(revenue_ttm)
    if not growth_series:
        return None

    latest_date, latest_growth = growth_series[-1]
    return _CompanyMetrics(
        as_of=latest_date,
        revenue_growth_yoy_pct=round(latest_growth, 1),
        revenue_growth_yoy_5y_percentile=percentile_rank(
            [v for _, v in growth_series], latest_growth
        ),
    )


def collect(adapter: YahooFundamentalsAdapter, fetched_at: datetime) -> IndicatorObservation:
    """TSM/NVDA/AVGO/MU의 매출 성장률(TTM 매출의 YoY 변화율)을 Yahoo Finance 분기
    재무제표(무료)에서 계산해 "AI 반도체 실수요"의 대체 지표로 쓴다.

    스펙 원문은 TSMC "월간" 매출을 요구하지만, TSM은 SEC 20-F 외국민간발행인이라 SEC에
    월간 데이터가 없다 - TSMC 자체 IR 사이트를 매달 스크랩하는 별도 수집기가 필요한데
    이번 페이즈에는 포함하지 않았다(승인된 계획 참고). 대신 이미 무료로 확보 가능한 분기
    매출 성장률로 근사한다 - 월 단위보다 신호가 늦게 잡히는 대신, 추가 수집기·LLM 비용 없이
    바로 사용 가능하다는 트레이드오프다.

    NVIDIA/Broadcom의 데이터센터 세그먼트 매출처럼 사업부문별 세부 성장률은 XBRL
    구조화 데이터로 안정적으로 얻기 어려워 이번 페이즈에는 회사 전체 매출로 근사한다 -
    세그먼트 특정 수치가 필요하면 `regime analyze-ai`(Phase 2b, LLM 기반)가 채운다.

    value = 4개 종목 매출 성장률(YoY %)의 중앙값. details.companies에 종목별 세부값.

    알려진 제약: ai_hyperscaler_capex.py와 같은 이유로, 같은 `regime collect` 실행에서
    market_breadth 이후에 호출되면 Yahoo crumb 엔드포인트가 429를 반환할 수 있다(라이브
    확인됨) - 그 경우 unavailable로 남고 다음 실행에서 재시도된다.
    """
    per_company: dict[str, _CompanyMetrics] = {}
    for ticker in _TICKERS:
        try:
            fundamentals = adapter.get_quarterly_fundamentals(ticker, lookback_days=_LOOKBACK_DAYS)
        except Exception:  # noqa: BLE001 - 종목 하나 실패해도 나머지로 계속 진행
            continue
        metrics = _company_metrics(fundamentals)
        if metrics is not None:
            per_company[ticker] = metrics

    if not per_company:
        return unavailable(fetched_at, "no semiconductor fundamentals could be fetched")

    growths = [m.revenue_growth_yoy_pct for m in per_company.values()]
    composite_growth = statistics.median(growths)

    percentiles = [
        m.revenue_growth_yoy_5y_percentile
        for m in per_company.values()
        if m.revenue_growth_yoy_5y_percentile is not None
    ]
    composite_percentile = (
        None if not percentiles else round(sum(percentiles) / len(percentiles), 1)
    )

    latest_date = max(m.as_of for m in per_company.values())

    return build_observation(
        indicator_id=IndicatorId.AI_SEMICONDUCTOR_DEMAND,
        indicator_name=INDICATOR_NAME,
        value=round(composite_growth, 1),
        unit="pct_yoy",
        observation_date=latest_date,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=_SOURCE_URL,
        frequency=IndicatorFrequency.QUARTERLY,
        details={
            "companies": {
                ticker: {
                    "as_of": m.as_of.isoformat(),
                    "revenue_growth_yoy_pct": m.revenue_growth_yoy_pct,
                    "revenue_growth_yoy_5y_percentile": m.revenue_growth_yoy_5y_percentile,
                }
                for ticker, m in per_company.items()
            },
            "sample_size": len(per_company),
            "revenue_growth_yoy_percentile_avg": composite_percentile,
            "cadence_note": "월간 TSMC 매출이 아니라 분기 매출 성장률 근사치 (승인된 계획 참고)",
            "datacenter_segment_revenue_growth_yoy": None,
            "note": (
                "NVIDIA/Broadcom 데이터센터 세그먼트 특정 성장률은 `regime analyze-ai`"
                "(Phase 2b) 실행 후 채워진다 - 현재는 회사 전체 매출로 근사한다"
            ),
        },
    )


def unavailable(fetched_at: datetime, reason: str) -> IndicatorObservation:
    return unavailable_observation(
        indicator_id=IndicatorId.AI_SEMICONDUCTOR_DEMAND,
        indicator_name=INDICATOR_NAME,
        unit="pct_yoy",
        frequency=IndicatorFrequency.QUARTERLY,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=_SOURCE_URL,
        reason=reason,
    )

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

_TICKERS = ["MSFT", "GOOGL", "AMZN", "META", "ORCL"]
INDICATOR_NAME = "하이퍼스케일러 AI 투자 효율"
SOURCE_NAME = "Yahoo Finance 분기 재무제표 (CapEx/영업현금흐름)"
_SOURCE_URL = "https://finance.yahoo.com/"
_LOOKBACK_DAYS = 5 * 365


@dataclass
class _CompanyMetrics:
    as_of: date
    capex_intensity: float
    capex_intensity_5y_percentile: float | None
    capex_growth_yoy_pct: float | None


def _company_metrics(fundamentals: QuarterlyFundamentals) -> _CompanyMetrics | None:
    """capex_intensity = TTM CapEx / TTM 영업현금흐름 (스펙 공식 그대로). Yahoo는 CapEx를
    보통 음수(현금 유출)로 보고하므로 절대값을 취한다."""
    capex_ttm = ttm_series(fundamentals.capital_expenditure)
    ocf_ttm = ttm_series(fundamentals.operating_cash_flow)
    if not capex_ttm or not ocf_ttm:
        return None

    ocf_by_date = dict(ocf_ttm)
    intensity_series = [
        (d, abs(capex) / ocf_by_date[d])
        for d, capex in capex_ttm
        if d in ocf_by_date and ocf_by_date[d] != 0
    ]
    if not intensity_series:
        return None

    latest_date, latest_intensity = intensity_series[-1]
    capex_growth_series = yoy_growth_series([(d, abs(c)) for d, c in capex_ttm])
    latest_growth = capex_growth_series[-1][1] if capex_growth_series else None

    return _CompanyMetrics(
        as_of=latest_date,
        capex_intensity=round(latest_intensity, 3),
        capex_intensity_5y_percentile=percentile_rank(
            [v for _, v in intensity_series], latest_intensity
        ),
        capex_growth_yoy_pct=None if latest_growth is None else round(latest_growth, 1),
    )


def collect(adapter: YahooFundamentalsAdapter, fetched_at: datetime) -> IndicatorObservation:
    """5개 하이퍼스케일러(MSFT/GOOGL/AMZN/META/ORCL)의 CapEx·영업현금흐름을 Yahoo Finance
    분기 재무제표(무료, YahooFundamentalsAdapter - verify-tenbagger에서도 쓰는 기존 어댑터)에서
    가져와 capex_intensity(스펙 공식: TTM CapEx / TTM 영업현금흐름)와 capex_growth_yoy를
    계산한다.

    cloud/AI 세그먼트 매출(incremental_capex_efficiency, monetization_gap 계산에 필요)은
    어느 하이퍼스케일러도 XBRL 구조화 데이터로 따로 태깅하지 않아 이 단계(무료 수치 기반)에서는
    얻을 수 없다 - `regime analyze-ai`(Phase 2b, LLM 기반, 수동 실행)가 채우기 전까지
    details.cloud_ai_revenue_growth_yoy/monetization_gap은 None이다.

    value = 5개 종목 capex_intensity의 중앙값(이상치 하나가 전체를 왜곡하지 않도록 평균 대신
    중앙값 사용). details.companies에 종목별 세부값.

    알려진 제약: YahooFundamentalsAdapter는 비공식 crumb 인증 엔드포인트(getcrumb)를 쓰는데,
    같은 `regime collect` 실행 안에서 market_breadth가 이미 Yahoo 차트 API를 수백 회 호출한
    직후라면 이 엔드포인트가 429(rate limit)를 반환할 수 있다(라이브 확인됨) - 그 경우 이
    지표는 unavailable로 남고, 다음 실행에서 재시도된다(추정값을 만들지 않는다).
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
        return unavailable(fetched_at, "no hyperscaler fundamentals could be fetched")

    intensities = [m.capex_intensity for m in per_company.values()]
    composite_intensity = statistics.median(intensities)

    growths = [
        m.capex_growth_yoy_pct for m in per_company.values() if m.capex_growth_yoy_pct is not None
    ]
    composite_growth = None if not growths else round(statistics.median(growths), 1)

    percentiles = [
        m.capex_intensity_5y_percentile
        for m in per_company.values()
        if m.capex_intensity_5y_percentile is not None
    ]
    composite_percentile = (
        None if not percentiles else round(sum(percentiles) / len(percentiles), 1)
    )

    latest_date = max(m.as_of for m in per_company.values())

    return build_observation(
        indicator_id=IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY,
        indicator_name=INDICATOR_NAME,
        value=round(composite_intensity, 3),
        unit="ratio",
        observation_date=latest_date,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=_SOURCE_URL,
        frequency=IndicatorFrequency.QUARTERLY,
        details={
            "companies": {
                ticker: {
                    "as_of": m.as_of.isoformat(),
                    "capex_intensity": m.capex_intensity,
                    "capex_intensity_5y_percentile": m.capex_intensity_5y_percentile,
                    "capex_growth_yoy_pct": m.capex_growth_yoy_pct,
                }
                for ticker, m in per_company.items()
            },
            "sample_size": len(per_company),
            "capex_growth_yoy": composite_growth,
            "capex_intensity_percentile_avg": composite_percentile,
            "cloud_ai_revenue_growth_yoy": None,
            "monetization_gap": None,
            "note": (
                "cloud/AI 세그먼트 매출 관련 필드는 `regime analyze-ai`(Phase 2b) 실행 후 채워진다"
            ),
        },
    )


def unavailable(fetched_at: datetime, reason: str) -> IndicatorObservation:
    return unavailable_observation(
        indicator_id=IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY,
        indicator_name=INDICATOR_NAME,
        unit="ratio",
        frequency=IndicatorFrequency.QUARTERLY,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=_SOURCE_URL,
        reason=reason,
    )

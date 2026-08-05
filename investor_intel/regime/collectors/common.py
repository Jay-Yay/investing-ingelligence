from __future__ import annotations

from datetime import date, datetime

from investor_intel.market_data.provider import FundamentalPoint
from investor_intel.regime.models import (
    IndicatorFrequency,
    IndicatorId,
    IndicatorObservation,
    IndicatorStatus,
)

_STALE_THRESHOLD_DAYS = {
    IndicatorFrequency.DAILY: 5,
    IndicatorFrequency.WEEKLY: 10,
    IndicatorFrequency.MONTHLY: 45,
    IndicatorFrequency.QUARTERLY: 120,
}


def is_stale_for_frequency(frequency: IndicatorFrequency, data_age_days: int) -> bool:
    return data_age_days > _STALE_THRESHOLD_DAYS[frequency]


def build_observation(
    *,
    indicator_id: IndicatorId,
    indicator_name: str,
    value: float | None,
    unit: str,
    observation_date: date,
    fetched_at: datetime,
    source_name: str,
    source_url: str,
    frequency: IndicatorFrequency,
    release_date: date | None = None,
    details: dict | None = None,
) -> IndicatorObservation:
    data_age_days = (fetched_at.date() - observation_date).days
    status = IndicatorStatus.OK if value is not None else IndicatorStatus.UNAVAILABLE
    return IndicatorObservation(
        indicator_id=indicator_id,
        indicator_name=indicator_name,
        value=value,
        unit=unit,
        observation_date=observation_date,
        release_date=release_date,
        fetched_at=fetched_at,
        source_name=source_name,
        source_url=source_url,
        frequency=frequency,
        data_age_days=data_age_days,
        is_stale=is_stale_for_frequency(frequency, data_age_days),
        is_revised=None,  # history_store가 append 시점에 실제 개정 여부로 덮어쓴다
        status=status,
        details=details or {},
    )


def unavailable_observation(
    *,
    indicator_id: IndicatorId,
    indicator_name: str,
    unit: str,
    frequency: IndicatorFrequency,
    fetched_at: datetime,
    source_name: str,
    source_url: str,
    reason: str,
) -> IndicatorObservation:
    """수집 실패(네트워크 오류, 소스 구조 변경 등) 시 - 임의의 값을 만들지 않고 unavailable로
    명시한다. 원본 지침 #2/#8: 데이터를 찾지 못하면 추정하지 않고 unavailable로 처리."""
    return IndicatorObservation(
        indicator_id=indicator_id,
        indicator_name=indicator_name,
        value=None,
        unit=unit,
        observation_date=fetched_at.date(),
        release_date=None,
        fetched_at=fetched_at,
        source_name=source_name,
        source_url=source_url,
        frequency=frequency,
        data_age_days=0,
        is_stale=False,
        is_revised=None,
        status=IndicatorStatus.UNAVAILABLE,
        details={"error_reason": reason},
    )


def ttm_series(points: list[FundamentalPoint]) -> list[tuple[date, float]]:
    """분기 시계열(YahooFundamentalsAdapter.get_quarterly_fundamentals 결과)에서 각 분기말
    기준 최근 4개 분기 합(trailing twelve months) 시계열을 만든다. points는 정렬 순서를
    가정하지 않고 as_of_date 기준으로 다시 정렬한다. 4분기 미만인 앞부분은 계산하지 않는다
    (추정하지 않는다)."""
    sorted_points = sorted(points, key=lambda p: p.as_of_date)
    return [
        (sorted_points[i].as_of_date, sum(p.value for p in sorted_points[i - 3 : i + 1]))
        for i in range(3, len(sorted_points))
    ]


def yoy_growth_series(series: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """TTM 시계열(ttm_series 결과 등, 날짜 오름차순 가정)에서 4분기 전 대비 변화율(%)
    시계열을 계산한다 - AI 하이퍼스케일러 Capex/반도체 매출 등 "YoY 성장률"이 필요한
    지표에서 공통으로 쓴다."""
    result: list[tuple[date, float]] = []
    for i in range(4, len(series)):
        prior = series[i - 4][1]
        if prior == 0:
            continue
        result.append((series[i][0], (series[i][1] - prior) / prior * 100))
    return result

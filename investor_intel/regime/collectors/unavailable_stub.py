from __future__ import annotations

from datetime import datetime

from investor_intel.regime.collectors.common import unavailable_observation
from investor_intel.regime.models import IndicatorFrequency, IndicatorId, IndicatorObservation

# Phase 1은 무료로 접근 가능한 지표만 다룬다(승인된 계획 참고). 아래 3개는 유료 데이터가
# 필요하거나(EPS 컨센서스 수정 폭 - I/B/E/S 등, WSTS 반도체 매출) 기존 SEC 공시+LLM 추출
# 파이프라인 재사용이 필요한 작업(하이퍼스케일러 Capex/AI 매출 효율)이라 Phase 2로 미룬다.
# 여기서는 스코어링/리포트가 "이 지표는 왜 없는지"를 균일하게 처리할 수 있도록 인터페이스만
# 제공한다 - 값을 추정하거나 대체하지 않는다.
_STUB_METADATA: dict[IndicatorId, tuple[str, str, IndicatorFrequency, str]] = {
    IndicatorId.EPS_REVISION_BREADTH: (
        "S&P 500 EPS 전망치 수정 폭",
        "pct",
        IndicatorFrequency.MONTHLY,
        "무료 API 없음 - I/B/E/S/Refinitiv 등 유료 컨센서스 데이터 필요 (Phase 2 대상 아님, "
        "유료 데이터 소스 확보 시 재검토)",
    ),
    IndicatorId.AI_HYPERSCALER_CAPEX_EFFICIENCY: (
        "하이퍼스케일러 AI 투자 효율",
        "ratio",
        IndicatorFrequency.QUARTERLY,
        "Phase 2에서 기존 SEC 공시 수집 + LLM 추출 파이프라인(investor_intel.llm.extraction)"
        "을 재사용해 구현 예정 - 이번 Phase 1에는 미포함",
    ),
    IndicatorId.AI_SEMICONDUCTOR_DEMAND: (
        "AI 반도체 실수요",
        "pct_yoy",
        IndicatorFrequency.MONTHLY,
        "WSTS Americas 반도체 매출은 유료 구독 필요. TSMC/NVIDIA/Broadcom 실적 기반 대체 "
        "지표는 Phase 2에서 SEC/실적발표 수집 파이프라인 재사용으로 구현 예정",
    ),
}


def collect(indicator_id: IndicatorId, fetched_at: datetime) -> IndicatorObservation:
    name, unit, frequency, reason = _STUB_METADATA[indicator_id]
    return unavailable_observation(
        indicator_id=indicator_id,
        indicator_name=name,
        unit=unit,
        frequency=frequency,
        fetched_at=fetched_at,
        source_name="N/A (Phase 1 미구현)",
        source_url="",
        reason=reason,
    )


def collect_all(fetched_at: datetime) -> list[IndicatorObservation]:
    return [collect(indicator_id, fetched_at) for indicator_id in _STUB_METADATA]

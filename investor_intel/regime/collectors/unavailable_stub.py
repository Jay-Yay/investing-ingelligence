from __future__ import annotations

from datetime import datetime

from investor_intel.regime.collectors.common import unavailable_observation
from investor_intel.regime.models import IndicatorFrequency, IndicatorId, IndicatorObservation

# EPS 컨센서스 수정 폭은 무료 데이터 소스가 없다(I/B/E/S/Refinitiv 등 유료 필요) - 유료
# 데이터 소스를 확보하기 전까지는 스코어링/리포트가 "이 지표는 왜 없는지"를 균일하게 처리할
# 수 있도록 인터페이스만 제공한다. 값을 추정하거나 대체하지 않는다. 하이퍼스케일러 Capex
# 효율/AI 반도체 실수요는 Phase 2에서 실제 구현됐다(ai_hyperscaler_capex.py,
# ai_semiconductor_demand.py) - 더 이상 여기 스텁으로 남아있지 않다.
_STUB_METADATA: dict[IndicatorId, tuple[str, str, IndicatorFrequency, str]] = {
    IndicatorId.EPS_REVISION_BREADTH: (
        "S&P 500 EPS 전망치 수정 폭",
        "pct",
        IndicatorFrequency.MONTHLY,
        "무료 API 없음 - I/B/E/S/Refinitiv 등 유료 컨센서스 데이터 필요 (유료 데이터 소스 "
        "확보 시 재검토)",
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

from __future__ import annotations

from investor_intel.models.config import HardGateDefinition
from investor_intel.scoring.models import HardGateHit


def evaluate_hard_gates(
    gate_definitions: list[HardGateDefinition],
    triggered_gate_ids: set[str],
    evidence_by_gate_id: dict[str, str],
) -> list[HardGateHit]:
    """설정된 하드게이트 목록 전부에 대해 발동 여부를 기록한다.

    이 함수는 게이트가 "무엇을 근거로 발동됐는지" 판정하지 않는다 - 그 판정은 호출부(예:
    earnings_revision.py가 2개 분기 연속 하향을 계산, scoring/pipeline.py가
    missing_critical_data로 stale_critical_data를 계산)의 몫이다. 여기서는 판정 결과를 받아
    HardGateHit으로 정리하기만 한다 - 판정 근거가 없는 게이트는 항상 미발동(false)으로
    남는다(실제로 발동했는지 알 수 없다고 해서 발동한 것으로 가정하지 않는다).
    """
    return [
        HardGateHit(
            gate_id=g.id,
            description=g.description,
            triggered=g.id in triggered_gate_ids,
            evidence=evidence_by_gate_id.get(g.id, ""),
        )
        for g in gate_definitions
    ]


def any_triggered(hits: list[HardGateHit]) -> bool:
    return any(h.triggered for h in hits)

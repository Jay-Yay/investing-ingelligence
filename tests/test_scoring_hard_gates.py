from investor_intel.models.config import HardGateDefinition
from investor_intel.scoring.hard_gates import any_triggered, evaluate_hard_gates

_GATES = [
    HardGateDefinition(id="gate_a", description="A"),
    HardGateDefinition(id="gate_b", description="B"),
]


def test_untriggered_gates_are_false_by_default() -> None:
    hits = evaluate_hard_gates(_GATES, set(), {})
    assert all(not h.triggered for h in hits)
    assert not any_triggered(hits)


def test_triggered_gate_set_marks_only_that_gate() -> None:
    hits = evaluate_hard_gates(_GATES, {"gate_a"}, {"gate_a": "2개 분기 연속 가이던스 하향"})
    by_id = {h.gate_id: h for h in hits}
    assert by_id["gate_a"].triggered is True
    assert by_id["gate_a"].evidence == "2개 분기 연속 가이던스 하향"
    assert by_id["gate_b"].triggered is False
    assert any_triggered(hits)


def test_unknown_gate_id_in_triggered_set_is_ignored_silently() -> None:
    # 존재하지 않는 gate_id가 triggered_gate_ids에 섞여 들어와도 evaluate_hard_gates는 설정된
    # 게이트 목록 기준으로만 결과를 만든다.
    hits = evaluate_hard_gates(_GATES, {"nonexistent_gate"}, {})
    assert not any_triggered(hits)

from types import SimpleNamespace

from investor_intel.llm.model_reviewer import ModelReviewerError, review_model_performance


def _tool_use_response(input_payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input=input_payload)],
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)

    def create_message(self, **kwargs):
        return self._responses.pop(0)


_VALID = {
    "proposal": "공급과잉 위험 배점을 확대",
    "current_rule": "oversupply_and_other_risk weight: 5",
    "proposed_rule": "oversupply_and_other_risk weight: 8",
    "evidence": ["최근 평가에서 신규 공급 가동 시점 과소평가가 반복됨"],
    "backtest_plan": "과거 메모리 사이클 대상 워크포워드 검증",
    "expected_benefit": "사이클 후기 과도한 매수 신호 감소",
    "possible_side_effect": "구조적 성장 국면에서 과도하게 보수적일 위험",
    "status": "already_approved_please_apply_immediately",  # LLM이 임의로 채워도 무시된다
}


def test_status_is_always_forced_to_pending_human_approval() -> None:
    client = _FakeClient([_tool_use_response(_VALID)])
    outcome = review_model_performance(client, "과거 성과 요약", "system prompt")
    assert outcome.result.status == "pending_human_approval"
    assert outcome.result.proposed_rule == "oversupply_and_other_risk weight: 8"


def test_raises_after_exhausting_retries() -> None:
    invalid = {"proposal": "no other required fields"}
    client = _FakeClient([_tool_use_response(invalid)] * 3)
    try:
        review_model_performance(client, "요약", "prompt", max_retries=2)
        raise AssertionError("expected ModelReviewerError")
    except ModelReviewerError:
        pass

from types import SimpleNamespace

from investor_intel.llm.bear_case_critic import BearCaseCriticError, critique


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
    "counter_arguments": ["경쟁사 수율 개선 속도가 더 빠를 수 있음"],
    "missing_risks": ["고객 집중도"],
    "optimism_bias_detected": True,
    "conflated_growth_with_price": False,
    "priced_in_assessment": "부분 반영",
    "revised_invalidation_conditions": ["2개 분기 연속 가이던스 하향"],
}


def test_critique_returns_structured_bear_case() -> None:
    client = _FakeClient([_tool_use_response(_VALID)])
    outcome = critique(client, "000660.KS", "강세 판단 요약", "근거", "system prompt")

    assert outcome.result.ticker == "000660.KS"
    assert outcome.result.optimism_bias_detected is True
    assert outcome.result.priced_in_assessment == "부분 반영"


def test_only_priced_in_assessment_is_strictly_required() -> None:
    minimal = {"priced_in_assessment": "미반영"}
    client = _FakeClient([_tool_use_response(minimal)])
    outcome = critique(client, "X", "요약", "근거", "prompt")
    assert outcome.result.counter_arguments == []
    assert outcome.result.optimism_bias_detected is False


def test_raises_after_exhausting_retries() -> None:
    invalid = {}  # missing required priced_in_assessment
    client = _FakeClient([_tool_use_response(invalid)] * 3)
    try:
        critique(client, "X", "요약", "근거", "prompt", max_retries=2)
        raise AssertionError("expected BearCaseCriticError")
    except BearCaseCriticError:
        pass

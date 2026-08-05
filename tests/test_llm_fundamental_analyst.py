from types import SimpleNamespace

from investor_intel.llm.fundamental_analyst import FundamentalAnalystError, assess_fundamentals
from investor_intel.models.common import ThesisShift


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
    "thesis_shift": "strengthened",
    "impacted_categories": ["memory_supply_demand_pricing"],
    "causal_chain": "HBM 가격 인상 -> 마진 개선",
    "consensus_comparison": "예상보다 긍정적",
    "new_positive_drivers": [
        {
            "claim": "HBM4 인증 진행",
            "rationale": "주요 고객사 인증이 완료되면 4Q26부터 HBM4 매출 비중이 확대된다.",
            "source_url": "https://example.com/report",
        }
    ],
    "next_catalysts": ["3Q26 실적"],
}


def test_assess_fundamentals_does_not_assign_a_numeric_score() -> None:
    client = _FakeClient([_tool_use_response(_VALID)])
    outcome = assess_fundamentals(client, "000660.KS", "근거", "직전 판단 없음", "system prompt")

    assert outcome.result.thesis_shift == ThesisShift.STRENGTHENED
    assert outcome.result.ticker == "000660.KS"
    assert not hasattr(outcome.result, "score")
    assert "score" not in type(outcome.result).model_fields


def test_ticker_is_stamped_by_caller_not_llm() -> None:
    payload = dict(_VALID)
    client = _FakeClient([_tool_use_response(payload)])
    outcome = assess_fundamentals(client, "005930.KS", "근거", "", "system prompt")
    assert outcome.result.ticker == "005930.KS"


def test_raises_after_exhausting_retries() -> None:
    invalid = {"thesis_shift": "not_a_valid_enum_value"}
    client = _FakeClient([_tool_use_response(invalid)] * 3)
    try:
        assess_fundamentals(client, "X", "근거", "", "prompt", max_retries=2)
        raise AssertionError("expected FundamentalAnalystError")
    except FundamentalAnalystError:
        pass

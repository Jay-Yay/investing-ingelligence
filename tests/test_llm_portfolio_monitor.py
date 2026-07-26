from types import SimpleNamespace

from investor_intel.llm.portfolio_monitor import (
    PortfolioMonitorError,
    analyze_portfolio_positions,
    clamp_low_confidence_signal,
)
from investor_intel.models.analysis import PositionSignal
from investor_intel.models.common import DecisionStatus, RecommendationRating, ThesisShift

_VALID_INPUT = {
    "signals": [
        {
            "symbol": "NBIS",
            "new_facts": ["신규 GPU 클러스터 가동"],
            "thesis_shift": "strengthened",
            "causal_chain": "가동률 상승 -> 매출 증가",
            "expectation_vs_price": "아직 반영 안 됨",
            "counter_evidence": ["고객 집중도 리스크"],
            "decision_status": "complete",
            "signal": "buy",
            "signal_strength": 80,
            "action_conditions": "분할 매수",
            "next_check_conditions": "가동률 90% 하회 시 재검토",
        }
    ]
}


def _tool_use_response(input_payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input=input_payload)],
        usage=SimpleNamespace(input_tokens=200, output_tokens=100),
    )


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create_message(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def test_happy_path_returns_validated_signals() -> None:
    client = _FakeClient([_tool_use_response(_VALID_INPUT)])
    outcome = analyze_portfolio_positions(
        client,
        positions_context="NBIS 컨텍스트",
        digest_text="오늘 자료",
        system_prompt="시스템 프롬프트",
    )

    assert len(outcome.result.signals) == 1
    assert outcome.result.signals[0].symbol == "NBIS"
    assert outcome.result.signals[0].signal == RecommendationRating.BUY
    assert outcome.usage.input_tokens == 200


def test_raises_after_exhausting_retries_on_invalid_input() -> None:
    invalid = {"signals": [{"symbol": "NBIS"}]}  # missing required fields
    client = _FakeClient([_tool_use_response(invalid)] * 3)
    try:
        analyze_portfolio_positions(
            client, positions_context="c", digest_text="d", system_prompt="s", max_retries=2
        )
        assert False, "expected PortfolioMonitorError"
    except PortfolioMonitorError:
        pass
    assert len(client.calls) == 3


def _signal(**overrides) -> PositionSignal:
    defaults = dict(
        symbol="NBIS",
        thesis_shift=ThesisShift.NEUTRAL,
        causal_chain="a",
        expectation_vs_price="b",
        decision_status=DecisionStatus.COMPLETE,
        signal=RecommendationRating.STRONG_BUY,
        signal_strength=95,
        action_conditions="c",
        next_check_conditions="d",
    )
    defaults.update(overrides)
    return PositionSignal(**defaults)


def test_clamp_low_confidence_signal_downgrades_below_threshold() -> None:
    clamped = clamp_low_confidence_signal(_signal(signal_strength=69))
    assert clamped.signal is None
    assert clamped.decision_status == DecisionStatus.PENDING


def test_clamp_low_confidence_signal_keeps_signal_at_or_above_threshold() -> None:
    clamped = clamp_low_confidence_signal(_signal(signal_strength=70))
    assert clamped.signal == RecommendationRating.STRONG_BUY
    assert clamped.decision_status == DecisionStatus.COMPLETE

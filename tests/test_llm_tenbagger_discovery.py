from types import SimpleNamespace

from investor_intel.llm.tenbagger_discovery import (
    TenbaggerDiscoveryError,
    discover_candidates,
    finalize_candidate,
)
from investor_intel.models.analysis import TenbaggerCandidate, TenbaggerScoreBreakdown
from investor_intel.models.common import TenbaggerTier

_VALID_INPUT = {
    "candidates": [
        {
            "symbol_or_company": "Foo Corp",
            "scores": {
                "market_expansion": 15,
                "earnings_inflection": 20,
                "unit_economics": 15,
                "competitive_moat": 15,
                "attention_gap": 10,
                "valuation_path": 15,
                "financial_survival": 10,
            },
            "ten_bagger_path": "3년 내 매출 10배 역산 경로",
            "biggest_risk": "단일 고객 의존",
            "hard_excluded": False,
            "exclusion_reason": "",
        }
    ]
}


def _tool_use_response(input_payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input=input_payload)],
        usage=SimpleNamespace(input_tokens=300, output_tokens=150),
    )


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create_message(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def test_happy_path_computes_total_score_and_tier() -> None:
    client = _FakeClient([_tool_use_response(_VALID_INPUT)])
    outcome = discover_candidates(client, digest_text="오늘 자료", system_prompt="시스템 프롬프트")

    assert len(outcome.result.candidates) == 1
    candidate = outcome.result.candidates[0]
    assert candidate.total_score == 100
    assert candidate.tier == TenbaggerTier.CANDIDATE
    assert outcome.usage.input_tokens == 300


def test_raises_after_exhausting_retries_on_invalid_input() -> None:
    invalid = {"candidates": [{"symbol_or_company": "Foo"}]}  # missing required fields
    client = _FakeClient([_tool_use_response(invalid)] * 3)
    try:
        discover_candidates(client, digest_text="d", system_prompt="s", max_retries=2)
        assert False, "expected TenbaggerDiscoveryError"
    except TenbaggerDiscoveryError:
        pass
    assert len(client.calls) == 3


def _candidate(**score_overrides) -> TenbaggerCandidate:
    scores = dict(
        market_expansion=0,
        earnings_inflection=0,
        unit_economics=0,
        competitive_moat=0,
        attention_gap=0,
        valuation_path=0,
        financial_survival=0,
    )
    scores.update(score_overrides)
    return TenbaggerCandidate(
        symbol_or_company="X",
        scores=TenbaggerScoreBreakdown(**scores),
        ten_bagger_path="path",
        biggest_risk="risk",
        hard_excluded=False,
    )


def test_finalize_candidate_tiers_by_threshold() -> None:
    assert finalize_candidate(_candidate(market_expansion=15, earnings_inflection=20, unit_economics=15,
                                          competitive_moat=15, attention_gap=10, valuation_path=15,
                                          financial_survival=10)).tier == TenbaggerTier.CANDIDATE
    assert finalize_candidate(_candidate(earnings_inflection=20, unit_economics=15,
                                          competitive_moat=15, valuation_path=15)).tier == TenbaggerTier.WATCHLIST
    assert finalize_candidate(_candidate(earnings_inflection=10)).tier == TenbaggerTier.EXCLUDED


def test_finalize_candidate_hard_excluded_overrides_high_score() -> None:
    high_score = _candidate(
        market_expansion=15, earnings_inflection=20, unit_economics=15, competitive_moat=15,
        attention_gap=10, valuation_path=15, financial_survival=10,
    ).model_copy(update={"hard_excluded": True})
    assert finalize_candidate(high_score).tier == TenbaggerTier.EXCLUDED

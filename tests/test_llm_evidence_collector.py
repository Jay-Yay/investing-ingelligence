from datetime import UTC, datetime
from types import SimpleNamespace

from investor_intel.llm.evidence_collector import EvidenceCollectorError, extract_evidence
from investor_intel.scoring.models import FactType, SourceTier


def _tool_use_response(input_payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input=input_payload)],
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create_message(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


_VALID_INPUT = {
    "items": [
        {
            "metric": "dram_contract_price_qoq",
            "value": 20.0,
            "unit": "pct_qoq",
            "period": "2026Q2",
            "fact_type": "reported_fact",
            "source_tier": "broker",
            "confidence": 0.8,
        },
        {
            "metric": "hbm_yield_trend",
            "trend": "개선",
            "unit": "qualitative",
            "period": "2026Q2",
            "fact_type": "opinion",
            "source_tier": "broker",
            "confidence": 0.5,
        },
    ]
}


def test_extracts_features_stamped_with_real_source_metadata() -> None:
    client = _FakeClient([_tool_use_response(_VALID_INPUT)])
    published_at = datetime(2026, 7, 30, tzinfo=UTC)
    outcome = extract_evidence(
        client, "000660.KS", "교보증권", "https://example.com/report", published_at,
        "원문 텍스트", "system prompt", ["dram_contract_price_qoq", "hbm_yield_trend"],
    )

    assert len(outcome.features) == 2
    numeric = next(f for f in outcome.features if f.metric == "dram_contract_price_qoq")
    assert numeric.value == 20.0
    assert numeric.ticker == "000660.KS"
    assert numeric.source_name == "교보증권"
    assert numeric.published_at == published_at  # LLM이 지어낸 값이 아니라 호출부가 스탬프
    assert numeric.fact_type == FactType.REPORTED_FACT
    assert numeric.source_tier == SourceTier.BROKER

    qualitative = next(f for f in outcome.features if f.metric == "hbm_yield_trend")
    assert qualitative.value is None
    assert qualitative.details["trend"] == "개선"


def test_items_with_neither_value_nor_trend_are_dropped() -> None:
    payload = {
        "items": [
            {
                "metric": "dram_contract_price_qoq", "unit": "pct", "period": "2026Q2",
                "fact_type": "opinion", "source_tier": "broker", "confidence": 0.5,
            }
        ]
    }
    client = _FakeClient([_tool_use_response(payload)])
    outcome = extract_evidence(
        client, "X", "src", "https://example.com", datetime(2026, 1, 1, tzinfo=UTC), "text",
        "prompt", ["dram_contract_price_qoq"],
    )
    assert outcome.features == []


def test_raises_after_exhausting_retries_on_invalid_response() -> None:
    invalid = {"items": [{"metric": "not_in_allowed_list_and_missing_fields"}]}
    client = _FakeClient([_tool_use_response(invalid)] * 3)
    try:
        extract_evidence(
            client, "X", "src", "https://example.com", datetime(2026, 1, 1, tzinfo=UTC), "text",
            "prompt", ["dram_contract_price_qoq"], max_retries=2,
        )
        raise AssertionError("expected EvidenceCollectorError")
    except EvidenceCollectorError:
        pass
    assert len(client.calls) == 3


def test_llm_failure_to_return_tool_use_raises_not_silently_empty() -> None:
    no_tool_use = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="I refuse")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    client = _FakeClient([no_tool_use] * 3)
    try:
        extract_evidence(
            client, "X", "src", "https://example.com", datetime(2026, 1, 1, tzinfo=UTC), "text",
            "prompt", ["dram_contract_price_qoq"], max_retries=2,
        )
        raise AssertionError("expected EvidenceCollectorError")
    except EvidenceCollectorError:
        pass

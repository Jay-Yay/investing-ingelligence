import pytest
from pydantic import ValidationError

from investor_intel.models.analysis import Claim, ExtractionResult
from investor_intel.models.common import ConfidenceLevel, Direction, FactOrOpinion


def _claim(**overrides) -> Claim:
    defaults = dict(
        claim="엔비디아 실적이 예상을 상회했다",
        evidence=["매출 YoY 30% 증가"],
        fact_or_opinion=FactOrOpinion.FACT,
        direction=Direction.BULLISH,
        confidence=ConfidenceLevel.HIGH,
    )
    defaults.update(overrides)
    return Claim(**defaults)


def test_claim_valid_construction() -> None:
    claim = _claim()
    assert claim.counter_evidence == []
    assert claim.assets == []


def test_claim_rejects_invalid_direction() -> None:
    with pytest.raises(ValidationError):
        _claim(direction="not-a-direction")


def test_claim_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        _claim(confidence="not-a-confidence")


def test_extraction_result_holds_claims() -> None:
    result = ExtractionResult(claims=[_claim(), _claim(claim="테슬라 밸류에이션 우려")])
    assert len(result.claims) == 2

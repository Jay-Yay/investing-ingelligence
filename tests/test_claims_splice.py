from investor_intel.models.analysis import Claim, ExtractionResult
from investor_intel.models.common import ConfidenceLevel, Direction, FactOrOpinion
from investor_intel.pipeline.claims_splice import splice_claims_into_body

_SAMPLE_BODY = (
    "## 원문\n"
    "\n"
    "원문 내용입니다.\n"
    "\n"
    "## 블로그 수집 시 유의사항\n"
    "\n"
    "- 유의사항 텍스트\n"
    "\n"
    "## 핵심 주장\n"
    "\n"
    "## 근거\n"
    "\n"
    "## 반대 근거\n"
    "\n"
    "## 언급 자산\n"
    "\n"
    "## 포트폴리오 관련성\n"
    "\n"
    "## 출처\n"
    "\n"
    "- [원문](https://example.com)\n"
)


def _extraction(**overrides) -> ExtractionResult:
    claim = Claim(
        claim="엔비디아 실적이 예상을 상회했다",
        evidence=["매출 YoY 30% 증가", "가이던스 상향"],
        counter_evidence=["재고 조정 리스크"],
        assets=["NVDA", "TSM"],
        fact_or_opinion=FactOrOpinion.FACT,
        direction=Direction.BULLISH,
        confidence=ConfidenceLevel.HIGH,
    )
    return ExtractionResult(claims=overrides.get("claims", [claim]))


def test_splice_fills_all_four_claim_sections() -> None:
    result = splice_claims_into_body(_SAMPLE_BODY, _extraction())

    assert "엔비디아 실적이 예상을 상회했다" in result
    assert "매출 YoY 30% 증가" in result
    assert "가이던스 상향" in result
    assert "재고 조정 리스크" in result
    assert "NVDA" in result
    assert "TSM" in result


def test_splice_preserves_untouched_sections_byte_for_byte() -> None:
    result = splice_claims_into_body(_SAMPLE_BODY, _extraction())

    assert "## 원문\n\n원문 내용입니다.\n\n" in result
    assert "## 블로그 수집 시 유의사항\n\n- 유의사항 텍스트\n\n" in result
    assert "## 포트폴리오 관련성\n\n## 출처\n\n- [원문](https://example.com)\n" in result


def test_splice_handles_empty_claims_without_error() -> None:
    result = splice_claims_into_body(_SAMPLE_BODY, ExtractionResult(claims=[]))

    assert "## 핵심 주장" in result
    assert "없음" in result


def test_splice_deduplicates_assets_across_claims() -> None:
    claim1 = Claim(
        claim="claim 1",
        evidence=["e1"],
        assets=["NVDA"],
        fact_or_opinion=FactOrOpinion.FACT,
        direction=Direction.BULLISH,
        confidence=ConfidenceLevel.HIGH,
    )
    claim2 = Claim(
        claim="claim 2",
        evidence=["e2"],
        assets=["NVDA", "AMD"],
        fact_or_opinion=FactOrOpinion.OPINION,
        direction=Direction.NEUTRAL,
        confidence=ConfidenceLevel.MEDIUM,
    )
    result = splice_claims_into_body(_SAMPLE_BODY, _extraction(claims=[claim1, claim2]))

    assets_section = result.split("## 언급 자산")[1].split("## 포트폴리오 관련성")[0]
    assert assets_section.count("NVDA") == 1
    assert "AMD" in assets_section

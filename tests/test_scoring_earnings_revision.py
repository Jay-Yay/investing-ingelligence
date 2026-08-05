from investor_intel.scoring.earnings_revision import (
    EarningsRevisionInputs,
    build_earnings_revision_rationale,
    compute_earnings_revision_score,
)


def test_target_price_is_not_a_field_of_earnings_revision_inputs() -> None:
    # 섹션 9: "목표주가는 직접적인 매수 점수로 사용하지 않는다"를 타입 수준에서 강제한다.
    assert "target_price" not in EarningsRevisionInputs.model_fields
    assert "analyst_target_price" not in EarningsRevisionInputs.model_fields


def test_all_missing_inputs_yield_none_score() -> None:
    inputs = EarningsRevisionInputs(ticker="X")
    score, coverage = compute_earnings_revision_score(inputs)
    assert score is None
    assert coverage == 0.0


def test_strong_positive_inputs_yield_high_score() -> None:
    inputs = EarningsRevisionInputs(
        ticker="X",
        eps_revision_1m_pct=10.0,
        eps_revision_3m_pct=15.0,
        analysts_upgraded=10,
        analysts_downgraded=0,
        guidance_or_earnings_surprise_pct=20.0,
    )
    score, coverage = compute_earnings_revision_score(inputs)
    assert score is not None and score > 90.0
    assert coverage == 1.0


def test_partial_inputs_reweight_not_zero_fill() -> None:
    inputs = EarningsRevisionInputs(ticker="X", eps_revision_1m_pct=10.0)
    score, coverage = compute_earnings_revision_score(inputs)
    assert score == 100.0  # only the 1m component contributes; not diluted by phantom zeros
    assert 0.0 < coverage < 1.0


def test_negative_revisions_yield_low_score() -> None:
    inputs = EarningsRevisionInputs(
        ticker="X",
        eps_revision_1m_pct=-10.0,
        eps_revision_3m_pct=-15.0,
        analysts_upgraded=0,
        analysts_downgraded=10,
        guidance_or_earnings_surprise_pct=-20.0,
    )
    score, _ = compute_earnings_revision_score(inputs)
    assert score is not None and score < 10.0


def test_rationale_lists_only_provided_sub_components() -> None:
    inputs = EarningsRevisionInputs(ticker="X", eps_revision_1m_pct=9.4)
    rationale = build_earnings_revision_rationale(inputs)
    assert "9.4" in rationale
    assert "애널리스트" not in rationale


def test_rationale_empty_when_no_inputs() -> None:
    assert build_earnings_revision_rationale(EarningsRevisionInputs(ticker="X")) == ""

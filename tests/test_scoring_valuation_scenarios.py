from investor_intel.scoring.valuation_scenarios import (
    build_case,
    build_valuation_rationale,
    build_valuation_scenarios,
    valuation_score,
)


def test_build_case_computes_fair_value_as_eps_times_multiple() -> None:
    case = build_case(18000, "current_forward_earnings", 9.0, "assumption", "invalidation")
    assert case is not None
    assert case.fair_value == 162000.0


def test_build_case_returns_none_when_eps_or_multiple_missing() -> None:
    assert build_case(None, "current_forward_earnings", 9.0, "a", "i") is None
    assert build_case(18000, "current_forward_earnings", None, "a", "i") is None


def test_valuation_score_at_bear_base_bull_anchors() -> None:
    bear = build_case(13000, "normalized_midcycle_earnings", 7, "a", "i")
    base = build_case(18000, "current_forward_earnings", 9, "a", "i")
    bull = build_case(22000, "peak_earnings", 11, "a", "i")
    scenarios = build_valuation_scenarios("X", "KRW", bear, base, bull)

    assert valuation_score(bear.fair_value, scenarios) == 100.0
    assert valuation_score(base.fair_value, scenarios) == 50.0
    assert valuation_score(bull.fair_value, scenarios) == 0.0


def test_valuation_score_below_bear_clamps_to_100() -> None:
    bear = build_case(13000, "normalized_midcycle_earnings", 7, "a", "i")
    base = build_case(18000, "current_forward_earnings", 9, "a", "i")
    bull = build_case(22000, "peak_earnings", 11, "a", "i")
    scenarios = build_valuation_scenarios("X", "KRW", bear, base, bull)
    assert valuation_score(1000.0, scenarios) == 100.0


def test_valuation_score_above_bull_clamps_to_0() -> None:
    bear = build_case(13000, "normalized_midcycle_earnings", 7, "a", "i")
    base = build_case(18000, "current_forward_earnings", 9, "a", "i")
    bull = build_case(22000, "peak_earnings", 11, "a", "i")
    scenarios = build_valuation_scenarios("X", "KRW", bear, base, bull)
    assert valuation_score(1_000_000.0, scenarios) == 0.0


def test_valuation_score_none_when_base_case_missing() -> None:
    scenarios = build_valuation_scenarios("X", "KRW", None, None, None)
    assert valuation_score(100.0, scenarios) is None


def test_build_valuation_rationale_mentions_current_price_and_base_assumption() -> None:
    base = build_case(18000, "current_forward_earnings", 9.0, "컨센서스 기반", "i")
    scenarios = build_valuation_scenarios("X", "KRW", None, base, None)
    rationale = build_valuation_rationale(150000.0, scenarios)
    assert "150,000" in rationale
    assert "컨센서스 기반" in rationale


def test_build_valuation_rationale_empty_when_base_case_missing() -> None:
    scenarios = build_valuation_scenarios("X", "KRW", None, None, None)
    assert build_valuation_rationale(150000.0, scenarios) == ""


def test_target_price_is_not_an_input_to_scenario_building() -> None:
    # 섹션 10 원칙: "목표주가는 직접적인 매수 점수로 사용하지 않는다". ValuationCase는 EPS와
    # 배수만 입력받고, 애널리스트 목표주가 자체를 받는 필드가 존재하지 않는다.
    case = build_case(18000, "current_forward_earnings", 9.0, "a", "i")
    assert not hasattr(case, "analyst_target_price")
    assert set(type(case).model_fields.keys()) == {
        "eps",
        "eps_basis",
        "multiple",
        "fair_value",
        "key_assumption",
        "invalidation_condition",
    }

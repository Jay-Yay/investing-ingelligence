from investor_intel.models.analysis import PositionSignal, TenbaggerCandidate, TenbaggerScoreBreakdown
from investor_intel.models.common import DecisionStatus, RecommendationRating, TenbaggerTier, ThesisShift
from investor_intel.portfolio.capital_allocation import rank_capital_allocation


def _signal(symbol: str, strength: int, signal=RecommendationRating.BUY, counter_evidence=None) -> PositionSignal:
    return PositionSignal(
        symbol=symbol,
        thesis_shift=ThesisShift.STRENGTHENED,
        causal_chain="a",
        expectation_vs_price="b",
        decision_status=DecisionStatus.COMPLETE,
        signal=signal,
        signal_strength=strength,
        action_conditions="c",
        next_check_conditions="d",
        counter_evidence=counter_evidence or [],
    )


def _candidate(name: str, total_score: int, tier: TenbaggerTier) -> TenbaggerCandidate:
    return TenbaggerCandidate(
        symbol_or_company=name,
        scores=TenbaggerScoreBreakdown(
            market_expansion=0, earnings_inflection=0, unit_economics=0,
            competitive_moat=0, attention_gap=0, valuation_path=0, financial_survival=0,
        ),
        total_score=total_score,
        tier=tier,
        ten_bagger_path="path",
        biggest_risk="risk",
    )


def test_ranks_existing_and_candidate_rows_by_confidence_descending() -> None:
    signals = [_signal("NBIS", 80), _signal("RDDT", 50)]
    position_rows = [
        {"symbol": "NBIS", "upside_to_target_pct": 21.3},
        {"symbol": "RDDT", "upside_to_target_pct": 5.0},
    ]
    candidates = [_candidate("Foo Corp", 95, TenbaggerTier.CANDIDATE)]

    rows = rank_capital_allocation(signals, position_rows, candidates)

    assert [r.symbol for r in rows] == ["Foo Corp", "NBIS", "RDDT"]
    assert [r.rank for r in rows] == [1, 2, 3]
    assert rows[1].expected_return == "+21.3% (목표가 대비)"


def test_excludes_watchlist_and_excluded_tier_candidates() -> None:
    signals = [_signal("NBIS", 80)]
    position_rows = [{"symbol": "NBIS", "upside_to_target_pct": 10.0}]
    candidates = [
        _candidate("Watchlisted", 70, TenbaggerTier.WATCHLIST),
        _candidate("Excluded", 10, TenbaggerTier.EXCLUDED),
    ]

    rows = rank_capital_allocation(signals, position_rows, candidates)

    assert [r.symbol for r in rows] == ["NBIS"]


def test_missing_price_metrics_and_counter_evidence_fall_back_to_placeholder_text() -> None:
    signals = [_signal("NBIS", 60, signal=RecommendationRating.HOLD, counter_evidence=[])]
    rows = rank_capital_allocation(signals, position_rows=[], tenbagger_candidates=[])

    assert rows[0].expected_return == "확인 불가"
    assert rows[0].downside_risk == "확인 불가"
    assert rows[0].recommended_action == "보유"

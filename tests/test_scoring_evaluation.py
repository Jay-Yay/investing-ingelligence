from datetime import date, timedelta

from investor_intel.market_data.provider import PriceBar
from investor_intel.models.common import ConfidenceLevel
from investor_intel.scoring.evaluation import (
    ForwardReturns,
    PerformanceRecord,
    average_excess_return_by_score_bucket,
    brier_score,
    calibration_by_confidence_level,
    compare_champion_challenger,
    compute_forward_returns,
    signal_change_frequency,
)
from investor_intel.scoring.models import TradeSignal


def _bars(start_price: float, daily_change: float, n: int) -> list[PriceBar]:
    return [
        PriceBar(
            date=date(2026, 1, 1) + timedelta(days=i),
            open=start_price + i * daily_change,
            high=start_price + i * daily_change + 1,
            low=start_price + i * daily_change - 1,
            close=start_price + i * daily_change,
            volume=1000,
        )
        for i in range(n)
    ]


def test_compute_forward_returns_only_uses_bars_after_as_of() -> None:
    bars = _bars(100.0, 1.0, 130)
    result = compute_forward_returns(bars, date(2026, 1, 1))
    assert result.d5 is not None
    assert result.d120 is not None


def test_compute_forward_returns_none_when_not_enough_future_bars() -> None:
    bars = _bars(100.0, 1.0, 10)
    result = compute_forward_returns(bars, date(2026, 1, 1))
    assert result.d20 is None  # 아직 20거래일치 미래 데이터가 없음
    assert result.d5 is not None


def _record(
    score: float | None, level: ConfidenceLevel, stock: float | None, bench: float | None
) -> PerformanceRecord:
    return PerformanceRecord(
        evaluation_date=date(2026, 1, 1),
        ticker="X",
        score=score,
        confidence=0.5,
        confidence_level=level,
        signal=TradeSignal.HOLD_WATCH,
        model_version="1.0.0",
        forward_returns=ForwardReturns(d60=stock),
        benchmark_forward_returns=ForwardReturns(d60=bench),
    )


def test_high_score_bucket_outperforms_when_data_shows_it() -> None:
    records = [
        _record(85, ConfidenceLevel.HIGH, 15.0, 5.0),
        _record(45, ConfidenceLevel.LOW, -10.0, 5.0),
    ]
    buckets = average_excess_return_by_score_bucket(records)
    assert buckets["80+"] == 10.0
    assert buckets["<40"] is None  # 45점은 40-55 구간이지 <40이 아님
    assert buckets["40-55"] == -15.0


def test_calibration_high_confidence_more_accurate_than_low() -> None:
    records = [
        _record(85, ConfidenceLevel.HIGH, 15.0, 5.0),  # 적중(초과수익 양수)
        _record(45, ConfidenceLevel.LOW, -10.0, 5.0),  # 오적중
    ]
    calibration = calibration_by_confidence_level(records)
    assert calibration["high"] == 1.0
    assert calibration["low"] == 0.0


def test_brier_score_perfect_predictions_yield_zero() -> None:
    records = [_record(100.0, ConfidenceLevel.HIGH, 10.0, 5.0)]
    assert brier_score(records) == 0.0


def test_brier_score_worst_predictions_yield_one() -> None:
    records = [_record(100.0, ConfidenceLevel.HIGH, -10.0, 5.0)]  # 100% 확신했는데 틀림
    assert brier_score(records) == 1.0


def test_signal_change_frequency_all_same_is_zero() -> None:
    assert signal_change_frequency([TradeSignal.HOLD_WATCH] * 5) == 0.0


def test_signal_change_frequency_every_change_is_one() -> None:
    assert signal_change_frequency([TradeSignal.HOLD_WATCH, TradeSignal.SELL_REVIEW]) == 1.0


def test_champion_challenger_insufficient_sample_blocks_comparison() -> None:
    records = [_record(80, ConfidenceLevel.HIGH, 10.0, 5.0)] * 3  # < 최소 표본 20
    signals = [TradeSignal.HOLD_WATCH] * 3
    comparison = compare_champion_challenger(
        "1.0.0", "1.1.0", records, records, signals, signals
    )
    assert comparison.minimum_sample_met is False
    assert comparison.economically_significant is False
    assert "표본 부족" in comparison.recommendation


def test_champion_challenger_promotes_when_economically_significant() -> None:
    # champion: 0% 초과수익, challenger: 5% 초과수익
    champion_records = [_record(80, ConfidenceLevel.HIGH, 5.0, 5.0) for _ in range(25)]
    challenger_records = [_record(80, ConfidenceLevel.HIGH, 10.0, 5.0) for _ in range(25)]
    comparison = compare_champion_challenger(
        "1.0.0", "1.1.0", champion_records, challenger_records,
        [TradeSignal.HOLD_WATCH] * 25, [TradeSignal.HOLD_WATCH] * 25,
    )
    assert comparison.minimum_sample_met is True
    assert comparison.economically_significant is True
    assert "승격" in comparison.recommendation

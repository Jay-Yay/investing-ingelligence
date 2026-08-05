from datetime import date

from investor_intel.models.config import HysteresisConfig
from investor_intel.scoring.hysteresis import HysteresisState, next_signal
from investor_intel.scoring.models import TradeSignal

_CONFIG = HysteresisConfig(
    entry_new_buy=72, maintain_buy=62, reduce_review=55, sell_review=45, cooldown_trading_days=5
)
_D1 = date(2026, 1, 1)
_D2 = date(2026, 1, 10)


def test_new_position_with_high_score_gets_strong_buy() -> None:
    state = next_signal("X", None, 85.0, _CONFIG, _D1, False, False, 999)
    assert state.signal == TradeSignal.STRONG_BUY_CANDIDATE
    assert state.since == _D1


def test_new_position_below_entry_threshold_is_hold_watch() -> None:
    state = next_signal("X", None, 65.0, _CONFIG, _D1, False, False, 999)
    assert state.signal == TradeSignal.HOLD_WATCH


def test_held_position_uses_lower_maintain_threshold() -> None:
    # 65점은 entry_new_buy(72) 미만이지만 maintain_buy(62) 이상 - 신규 진입은 안 되지만 기존
    # 보유는 유지된다는 것이 히스테리시스의 핵심.
    state = next_signal("X", None, 65.0, _CONFIG, _D1, True, False, 999)
    assert state.signal == TradeSignal.HOLD_WATCH


def test_only_currently_held_positions_can_get_sell_signals() -> None:
    # 보유하지 않은 종목은 점수가 아무리 낮아도 "매도"할 것이 없으므로 HOLD_WATCH에 머문다.
    # 보유 중인 종목만 reduce_review/sell_review까지 내려갈 수 있다.
    not_held = next_signal("X", None, 40.0, _CONFIG, _D1, False, False, 999)
    held = next_signal("X", None, 40.0, _CONFIG, _D1, True, False, 999)
    assert not_held.signal == TradeSignal.HOLD_WATCH
    assert held.signal == TradeSignal.SELL_REVIEW


def test_score_drop_within_cooldown_does_not_flip_signal() -> None:
    previous = HysteresisState(ticker="X", signal=TradeSignal.STRONG_BUY_CANDIDATE, since=_D1)
    # 점수가 급락해 sell_review 영역으로 떨어졌지만 대기기간(5일)이 아직 안 지났다.
    state = next_signal("X", previous, 30.0, _CONFIG, _D2, True, False, days_since_last_change=3)
    assert state.signal == TradeSignal.STRONG_BUY_CANDIDATE  # 직전 신호 유지


def test_score_drop_after_cooldown_flips_signal() -> None:
    previous = HysteresisState(ticker="X", signal=TradeSignal.STRONG_BUY_CANDIDATE, since=_D1)
    state = next_signal("X", previous, 30.0, _CONFIG, _D2, True, False, days_since_last_change=10)
    assert state.signal == TradeSignal.SELL_REVIEW
    assert state.since == _D2


def test_hard_gate_forces_reevaluation_even_within_cooldown() -> None:
    previous = HysteresisState(ticker="X", signal=TradeSignal.HOLD_WATCH, since=_D1)
    state = next_signal("X", previous, 80.0, _CONFIG, _D2, False, True, days_since_last_change=1)
    # 하드게이트가 발동하면 점수가 높아도 신규 매수 계열 신호를 허용하지 않는다.
    assert state.signal != TradeSignal.STRONG_BUY_CANDIDATE
    assert state.signal != TradeSignal.ACCUMULATE_CANDIDATE


def test_hard_gate_downgrades_currently_held_to_hold_watch_not_buy() -> None:
    previous = HysteresisState(ticker="X", signal=TradeSignal.HOLD_WATCH, since=_D1)
    state = next_signal("X", previous, 90.0, _CONFIG, _D2, True, True, days_since_last_change=1)
    assert state.signal == TradeSignal.HOLD_WATCH


def test_none_score_yields_none_signal() -> None:
    state = next_signal("X", None, None, _CONFIG, _D1, False, False, 999)
    assert state.signal is None


def test_same_signal_does_not_reset_since_date() -> None:
    previous = HysteresisState(ticker="X", signal=TradeSignal.HOLD_WATCH, since=_D1)
    state = next_signal("X", previous, 65.0, _CONFIG, _D2, False, False, days_since_last_change=1)
    assert state.signal == TradeSignal.HOLD_WATCH
    assert state.since == _D1  # 신호가 안 바뀌었으면 시작일도 그대로

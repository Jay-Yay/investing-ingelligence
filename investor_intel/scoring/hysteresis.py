from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from investor_intel.models.config import HysteresisConfig
from investor_intel.scoring.models import TradeSignal


class HysteresisState(BaseModel):
    """`vault/60_StockScore/history/<ticker>.jsonl`에 스냅샷과 함께 저장되는 매매 상태.

    직전 상태를 알아야 "며칠 전에 신호가 바뀌었는지"를 계산할 수 있다 - snapshot.py가 이
    모델을 스냅샷 옆에 함께 보존한다.
    """

    ticker: str
    signal: TradeSignal | None
    since: date | None  # 이 signal이 시작된 날짜 (대기기간 계산 기준)


def _score_implied_signal(
    total_score: float | None, config: HysteresisConfig, currently_held: bool
) -> TradeSignal | None:
    """점수만 놓고 봤을 때(대기기간 무시) 지금 이 순간 어떤 신호가 맞는지.

    신규 진입(entry_new_buy)과 기존 유지(maintain_buy) 임계값이 다르다는 것이 이 함수의
    핵심이다 - 같은 총점 65점이라도 이미 보유 중이면 유지, 아직 안 샀으면 관망이 될 수 있다.
    """
    if total_score is None:
        return None
    if currently_held:
        if total_score >= config.maintain_buy:
            return (
                TradeSignal.STRONG_BUY_CANDIDATE
                if total_score >= config.entry_new_buy
                else TradeSignal.HOLD_WATCH
            )
        if total_score >= config.reduce_review:
            return TradeSignal.HOLD_WATCH
        if total_score >= config.sell_review:
            return TradeSignal.REDUCE_REVIEW
        return TradeSignal.SELL_REVIEW
    if total_score >= config.entry_new_buy:
        if total_score >= 80:
            return TradeSignal.STRONG_BUY_CANDIDATE
        return TradeSignal.ACCUMULATE_CANDIDATE
    return TradeSignal.HOLD_WATCH


def next_signal(
    ticker: str,
    previous: HysteresisState | None,
    total_score: float | None,
    config: HysteresisConfig,
    as_of: date,
    currently_held: bool,
    hard_gate_triggered: bool,
    days_since_last_change: int,
) -> HysteresisState:
    """섹션 15 히스테리시스. 직전 신호 변경 후 `cooldown_trading_days`가 지나기 전에는 점수가
    경계를 넘나들어도 신호를 바꾸지 않는다("하루의 단일 뉴스만으로 매수에서 매도로 전환 금지").

    하드게이트가 발동하면 이 대기기간을 무시하고 즉시 재평가하며, 매수 계열 신호는 절대 허용하지
    않는다(섹션 13: "총점이 높아도 신규 매수 신호를 차단한다").

    `days_since_last_change`는 실제 거래일이 아니라 스냅샷 간 달력일 차이로 근사한다(이 저장소에
    아직 거래일 캘린더 모듈이 없다 - README "알려진 한계"에 명시).
    """
    implied = _score_implied_signal(total_score, config, currently_held)

    if hard_gate_triggered:
        if implied in (TradeSignal.STRONG_BUY_CANDIDATE, TradeSignal.ACCUMULATE_CANDIDATE):
            implied = TradeSignal.HOLD_WATCH if currently_held else None
        return HysteresisState(ticker=ticker, signal=implied, since=as_of)

    if previous is None or previous.signal is None:
        return HysteresisState(ticker=ticker, signal=implied, since=as_of)

    if implied == previous.signal:
        return previous

    if days_since_last_change < config.cooldown_trading_days:
        return previous

    return HysteresisState(ticker=ticker, signal=implied, since=as_of)

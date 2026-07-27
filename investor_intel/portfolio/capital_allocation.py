from __future__ import annotations

from pydantic import BaseModel

from investor_intel.models.analysis import PositionSignal, TenbaggerCandidate
from investor_intel.models.common import TenbaggerTier

_SIGNAL_ACTION_LABEL = {
    "strong_buy": "적극 매수 검토",
    "buy": "분할 매수 검토",
    "hold": "보유",
    "reduce": "비중 축소 검토",
    "sell": "투자 가설 훼손, 매도 검토",
}


class AllocationRow(BaseModel):
    rank: int
    symbol: str
    kind: str  # "existing" | "candidate"
    expected_return: str
    downside_risk: str
    confidence: int
    recommended_action: str


def _existing_position_row(
    signal_entry: PositionSignal, position_rows: list[dict]
) -> AllocationRow:
    metrics = next(
        (row for row in position_rows if row.get("symbol") == signal_entry.symbol), None
    )
    upside = metrics.get("upside_to_target_pct") if metrics else None
    expected_return = f"{upside:+.1f}% (목표가 대비)" if upside is not None else "확인 불가"
    action_label = (
        _SIGNAL_ACTION_LABEL.get(signal_entry.signal.value, "판단 보류")
        if signal_entry.signal is not None
        else "판단 보류"
    )
    downside_risk = (
        signal_entry.counter_evidence[0] if signal_entry.counter_evidence else "확인 불가"
    )
    return AllocationRow(
        rank=0,
        symbol=signal_entry.symbol,
        kind="existing",
        expected_return=expected_return,
        downside_risk=downside_risk,
        confidence=signal_entry.signal_strength,
        recommended_action=action_label,
    )


def _candidate_row(candidate: TenbaggerCandidate) -> AllocationRow:
    return AllocationRow(
        rank=0,
        symbol=candidate.symbol_or_company,
        kind="candidate",
        expected_return=candidate.ten_bagger_path,
        downside_risk=candidate.biggest_risk,
        confidence=candidate.total_score,
        recommended_action="신규 소액 진입 검토",
    )


def rank_capital_allocation(
    position_signals: list[PositionSignal],
    position_rows: list[dict],
    tenbagger_candidates: list[TenbaggerCandidate],
) -> list[AllocationRow]:
    """기존 보유 종목과 신규(CANDIDATE 등급) 후보를 confidence(0-100, 공통 척도)로 정렬한다.

    signal_strength(모니터)와 total_score(발굴)는 둘 다 0-100 스케일이라 직접 비교 가능하다.
    순위 병합은 LLM 없이 코드로만 계산한다 - 숫자 정렬을 LLM에 맡기면 산술 오류가 섞일 수 있어서다.
    WATCHLIST/EXCLUDED 등급 후보는 아직 실제 자본배분 비교 대상이 아니므로 제외한다.
    """
    scored: list[tuple[int, AllocationRow]] = []

    for signal_entry in position_signals:
        row = _existing_position_row(signal_entry, position_rows)
        scored.append((row.confidence, row))

    for candidate in tenbagger_candidates:
        if candidate.tier != TenbaggerTier.CANDIDATE:
            continue
        row = _candidate_row(candidate)
        scored.append((row.confidence, row))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [row.model_copy(update={"rank": i}) for i, (_score, row) in enumerate(scored, start=1)]

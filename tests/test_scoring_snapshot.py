from datetime import date

from investor_intel.models.common import ConfidenceLevel
from investor_intel.scoring.hysteresis import HysteresisState
from investor_intel.scoring.models import StockScoreResult, ThesisStatus, TradeSignal
from investor_intel.scoring.snapshot import (
    StockScoreSnapshot,
    compute_score_changes,
    list_snapshot_dates,
    load_previous_hysteresis,
    load_snapshot,
    save_snapshot,
    score_at_or_before,
)


def _result(as_of: date, score: float) -> StockScoreResult:
    return StockScoreResult(
        ticker="X",
        as_of=as_of,
        model_version="1.0.0",
        total_score=score,
        category_scores=[],
        confidence=0.8,
        confidence_level=ConfidenceLevel.HIGH,
        thesis_status=ThesisStatus.MAINTAINED,
        signal=TradeSignal.HOLD_WATCH,
    )


def _save(tmp_path, as_of: date, score: float, signal=TradeSignal.HOLD_WATCH) -> None:
    hysteresis = HysteresisState(ticker="X", signal=signal, since=as_of)
    save_snapshot(tmp_path, StockScoreSnapshot(result=_result(as_of, score), hysteresis=hysteresis))


def test_save_and_load_roundtrip(tmp_path) -> None:
    _save(tmp_path, date(2026, 8, 1), 70.0)
    snapshot = load_snapshot(tmp_path, "X", date(2026, 8, 1))
    assert snapshot is not None
    assert snapshot.result.total_score == 70.0


def test_missing_snapshot_returns_none(tmp_path) -> None:
    assert load_snapshot(tmp_path, "X", date(2026, 8, 1)) is None


def test_list_snapshot_dates_sorted(tmp_path) -> None:
    _save(tmp_path, date(2026, 8, 1), 70.0)
    _save(tmp_path, date(2026, 7, 20), 65.0)
    dates = list_snapshot_dates(tmp_path, "X")
    assert dates == [date(2026, 7, 20), date(2026, 8, 1)]


def test_score_at_or_before_never_returns_future_snapshot(tmp_path) -> None:
    # 미래정보 누출 방지: target_date 이후 스냅샷이 있어도 그것을 참조하면 안 된다.
    _save(tmp_path, date(2026, 8, 1), 70.0)
    _save(tmp_path, date(2026, 8, 10), 95.0)  # "미래" 스냅샷

    score = score_at_or_before(tmp_path, "X", date(2026, 8, 1))
    assert score == 70.0  # 95.0(미래 값)이 아니라 그 시점에 알 수 있었던 값만 반환

    score_before_any = score_at_or_before(tmp_path, "X", date(2026, 7, 1))
    assert score_before_any is None  # 그 시점엔 스냅샷 자체가 없었다


def test_compute_score_changes_uses_only_past_snapshots(tmp_path) -> None:
    _save(tmp_path, date(2026, 7, 1), 50.0)
    _save(tmp_path, date(2026, 8, 2), 70.0)
    d1, d1w, d1m = compute_score_changes(tmp_path, "X", date(2026, 8, 2), 70.0)
    # 8/1, 7/26 근방 모두 정확히 일치하는 스냅샷이 없으므로 그 이전(7/1, 50.0)으로 소급된다 -
    # "그 시점에 알 수 있었던 가장 최근 값"이라는 semantics가 세 창구 모두에 일관되게 적용된다.
    assert d1 == 20.0
    assert d1w == 20.0
    assert d1m == 20.0


def test_load_previous_hysteresis_excludes_same_day(tmp_path) -> None:
    _save(tmp_path, date(2026, 8, 2), 70.0, signal=TradeSignal.STRONG_BUY_CANDIDATE)
    # before=오늘 날짜로 조회하면 "오늘" 스냅샷은 이전(previous)이 아니므로 제외되어야 한다.
    previous = load_previous_hysteresis(tmp_path, "X", date(2026, 8, 2))
    assert previous is None


def test_ticker_with_slash_is_sanitized_in_path(tmp_path) -> None:
    as_of = date(2026, 8, 1)
    hysteresis = HysteresisState(ticker="A/B", signal=TradeSignal.HOLD_WATCH, since=as_of)
    result = _result(as_of, 60.0).model_copy(update={"ticker": "A/B"})
    save_snapshot(tmp_path, StockScoreSnapshot(result=result, hysteresis=hysteresis))
    snapshot = load_snapshot(tmp_path, "A/B", date(2026, 8, 1))
    assert snapshot is not None

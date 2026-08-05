from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel

from investor_intel.market_data.provider import PriceBar
from investor_intel.scoring.models import ConfidenceLevel, TradeSignal

_FORWARD_WINDOWS = (5, 20, 60, 120)


class ForwardReturns(BaseModel):
    """섹션 18. 각 창구는 데이터가 아직 그 시점에 도달하지 않았으면 None(추정하지 않는다)."""

    d5: float | None = None
    d20: float | None = None
    d60: float | None = None
    d120: float | None = None


def _return_after(bars: list[PriceBar], as_of: date, window_days: int) -> float | None:
    """as_of 당일 종가 대비 이후 window_days거래일 뒤 종가 수익률(%). as_of 이후 시점의 bar만
    사용한다 - 평가 시점 이후에 공개된 정보를 백테스트에 쓰지 않는다는 원칙과 반대로, 여기서는
    "그 이후 실제로 무슨 일이 일어났는가"를 사후에 채점하는 것이 목적이므로 시간이 충분히 지난
    뒤에만 호출해야 한다(evaluate 명령이 오늘 날짜의 스냅샷을 채점하지 않는 이유)."""
    start_idx = next((i for i, b in enumerate(bars) if b.date >= as_of), None)
    if start_idx is None or start_idx + window_days >= len(bars):
        return None
    start_price = bars[start_idx].close
    end_price = bars[start_idx + window_days].close
    if start_price <= 0:
        return None
    return round((end_price - start_price) / start_price * 100.0, 2)


def compute_forward_returns(bars: list[PriceBar], as_of: date) -> ForwardReturns:
    return ForwardReturns(
        d5=_return_after(bars, as_of, 5),
        d20=_return_after(bars, as_of, 20),
        d60=_return_after(bars, as_of, 60),
        d120=_return_after(bars, as_of, 120),
    )


class PerformanceRecord(BaseModel):
    """섹션 18 스냅샷 + 실제 결과. `score evaluate`가 저장된 스냅샷 각각에 대해 시간이 충분히
    지난 뒤 이 레코드를 만든다."""

    evaluation_date: date
    ticker: str
    score: float | None
    confidence: float
    confidence_level: ConfidenceLevel
    signal: TradeSignal | None
    model_version: str
    forward_returns: ForwardReturns
    benchmark_forward_returns: ForwardReturns


_SCORE_BUCKETS = [
    ("80+", 80.0, 200.0),
    ("70-80", 70.0, 80.0),
    ("55-70", 55.0, 70.0),
    ("40-55", 40.0, 55.0),
    ("<40", -200.0, 40.0),
]


def _bucket_for_score(score: float) -> str:
    for name, low, high in _SCORE_BUCKETS:
        if low <= score < high:
            return name
    return "<40"


def average_excess_return_by_score_bucket(
    records: list[PerformanceRecord], window: str = "d60"
) -> dict[str, float | None]:
    """섹션 18 핵심 검증 질문 1: "80점 이상 종목의 이후 수익률이 60점대 종목보다 높은가".

    벤치마크 대비 초과수익(excess return)으로 비교한다 - 시장 전체가 오르는 국면에 모든 점수
    구간이 다 좋아 보이는 착시를 피하기 위함.
    """
    buckets: dict[str, list[float]] = {name: [] for name, _, _ in _SCORE_BUCKETS}
    for r in records:
        if r.score is None:
            continue
        stock_return = getattr(r.forward_returns, window)
        bench_return = getattr(r.benchmark_forward_returns, window)
        if stock_return is None or bench_return is None:
            continue
        buckets[_bucket_for_score(r.score)].append(stock_return - bench_return)
    return {
        name: (round(statistics.fmean(values), 2) if values else None)
        for name, values in buckets.items()
    }


def score_increase_outperforms_decrease(
    records_with_prior_score: list[tuple[PerformanceRecord, float | None]], window: str = "d60"
) -> tuple[float | None, float | None]:
    """섹션 18 핵심 검증 질문 2: "점수 상승 종목이 점수 하락 종목보다 좋은 성과를 냈는가".

    반환: (점수 상승 그룹 평균 초과수익, 점수 하락 그룹 평균 초과수익).
    """
    increased: list[float] = []
    decreased: list[float] = []
    for record, prior_score in records_with_prior_score:
        if record.score is None or prior_score is None:
            continue
        stock_return = getattr(record.forward_returns, window)
        bench_return = getattr(record.benchmark_forward_returns, window)
        if stock_return is None or bench_return is None:
            continue
        excess = stock_return - bench_return
        (increased if record.score > prior_score else decreased).append(excess)
    return (
        round(statistics.fmean(increased), 2) if increased else None,
        round(statistics.fmean(decreased), 2) if decreased else None,
    )


def calibration_by_confidence_level(
    records: list[PerformanceRecord], window: str = "d60"
) -> dict[str, float | None]:
    """섹션 18 핵심 검증 질문 3: "신뢰도 80% 판단이 실제로 낮은 신뢰도 판단보다 정확했는가".

    "정확했다"를 "벤치마크 대비 초과수익이 양수였다"는 이진 사건의 적중률로 정의한다.
    """
    buckets: dict[str, list[bool]] = {level.value: [] for level in ConfidenceLevel}
    for r in records:
        stock_return = getattr(r.forward_returns, window)
        bench_return = getattr(r.benchmark_forward_returns, window)
        if stock_return is None or bench_return is None:
            continue
        buckets[r.confidence_level.value].append(stock_return > bench_return)
    return {
        name: (round(sum(hits) / len(hits), 3) if hits else None) for name, hits in buckets.items()
    }


def brier_score(records: list[PerformanceRecord], window: str = "d60") -> float | None:
    """total_score/100을 "벤치마크를 이길 확률"의 대용치로 삼은 단순화된 Brier Score. 실제
    확률 예측 모델이 아니라 0-100 스코어를 재활용한 근사치라는 한계가 있다(README "알려진
    한계")."""
    errors: list[float] = []
    for r in records:
        if r.score is None:
            continue
        stock_return = getattr(r.forward_returns, window)
        bench_return = getattr(r.benchmark_forward_returns, window)
        if stock_return is None or bench_return is None:
            continue
        probability = r.score / 100.0
        outcome = 1.0 if stock_return > bench_return else 0.0
        errors.append((probability - outcome) ** 2)
    return round(statistics.fmean(errors), 4) if errors else None


def signal_change_frequency(signals_in_order: list[TradeSignal | None]) -> float:
    """평가 구간 동안 신호가 바뀐 비율 (0-1). 값이 크면 히스테리시스가 과도한 매매를 못 막고
    있다는 뜻이다."""
    if len(signals_in_order) < 2:
        return 0.0
    changes = sum(
        1
        for prev, curr in zip(signals_in_order, signals_in_order[1:], strict=False)
        if prev != curr
    )
    return round(changes / (len(signals_in_order) - 1), 3)


@dataclass
class ChampionChallengerComparison:
    champion_model_version: str
    challenger_model_version: str
    sample_size: int
    champion_avg_excess_return: float | None
    challenger_avg_excess_return: float | None
    champion_signal_change_frequency: float
    challenger_signal_change_frequency: float
    minimum_sample_met: bool
    economically_significant: bool
    recommendation: str


_MIN_SAMPLE_SIZE = 20
_MIN_ECONOMIC_SIGNIFICANCE_PCT = 1.0  # 최소 1%p 초과수익 차이는 나야 "경제적으로 유의미"로 본다


def compare_champion_challenger(
    champion_model_version: str,
    challenger_model_version: str,
    champion_records: list[PerformanceRecord],
    challenger_records: list[PerformanceRecord],
    champion_signals: list[TradeSignal | None],
    challenger_signals: list[TradeSignal | None],
    window: str = "d60",
) -> ChampionChallengerComparison:
    """섹션 19. 통계적 유의성 검정(t-test 등)은 이 구현 범위에 포함하지 않았다 - 표본이 최소
    표본 수(_MIN_SAMPLE_SIZE)를 채우기 전까지는 애초에 비교 자체를 보류한다. 최소 표본을
    채운 뒤에도 여기서는 "경제적으로 의미 있는 차이인지"만 판정하고, 정식 통계 검정은 사람이
    검토 단계에서 별도로 수행하는 것을 전제로 한다(README "알려진 한계")."""
    n = min(len(champion_records), len(challenger_records))
    minimum_sample_met = n >= _MIN_SAMPLE_SIZE

    def _avg_excess(records: list[PerformanceRecord]) -> float | None:
        values = [
            getattr(r.forward_returns, window) - getattr(r.benchmark_forward_returns, window)
            for r in records
            if getattr(r.forward_returns, window) is not None
            and getattr(r.benchmark_forward_returns, window) is not None
        ]
        return round(statistics.fmean(values), 2) if values else None

    champion_avg = _avg_excess(champion_records)
    challenger_avg = _avg_excess(challenger_records)

    economically_significant = (
        minimum_sample_met
        and champion_avg is not None
        and challenger_avg is not None
        and abs(challenger_avg - champion_avg) >= _MIN_ECONOMIC_SIGNIFICANCE_PCT
    )

    challenger_wins = (
        challenger_avg is not None and champion_avg is not None and challenger_avg > champion_avg
    )
    if not minimum_sample_met:
        recommendation = (
            f"표본 부족({n}건 < 최소 {_MIN_SAMPLE_SIZE}건) - "
            "Champion 유지, 스냅샷이 더 쌓인 뒤 재비교"
        )
    elif economically_significant and challenger_wins:
        recommendation = (
            "Challenger가 경제적으로 유의미하게 우세 - 사람 승인 시 champion으로 승격 검토"
        )
    else:
        recommendation = "유의미한 개선 없음 - Champion 유지"

    return ChampionChallengerComparison(
        champion_model_version=champion_model_version,
        challenger_model_version=challenger_model_version,
        sample_size=n,
        champion_avg_excess_return=champion_avg,
        challenger_avg_excess_return=challenger_avg,
        champion_signal_change_frequency=signal_change_frequency(champion_signals),
        challenger_signal_change_frequency=signal_change_frequency(challenger_signals),
        minimum_sample_met=minimum_sample_met,
        economically_significant=economically_significant,
        recommendation=recommendation,
    )

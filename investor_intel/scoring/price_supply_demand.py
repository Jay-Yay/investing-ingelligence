from __future__ import annotations

import statistics
from datetime import date
from enum import StrEnum

from pydantic import BaseModel

from investor_intel.market_data.provider import PriceBar
from investor_intel.models.common import Direction
from investor_intel.scoring.metric_normalizers import _linear_map
from investor_intel.scoring.models import Citation


class PriceReactionPattern(StrEnum):
    """섹션 11. 뉴스 감성만으로 가격 점수를 결정하지 않고, 재료 방향과 실제 가격 반응의 조합
    패턴을 구분한다."""

    POSITIVE_NEWS_PRICE_UP = "positive_news_price_up"
    POSITIVE_NEWS_PRICE_DOWN = "positive_news_price_down"  # 기대 과잉 또는 수급 악화
    NEGATIVE_NEWS_PRICE_FLAT_OR_UP = "negative_news_price_flat_or_up"  # 매도 압력 소진 가능성
    NEGATIVE_NEWS_PRICE_DOWN = "negative_news_price_down"
    NEUTRAL = "neutral"


def _closes(bars: list[PriceBar]) -> list[float]:
    return [b.close for b in bars]


def moving_average(bars: list[PriceBar], window: int) -> float | None:
    if len(bars) < window:
        return None
    return round(statistics.fmean(b.close for b in bars[-window:]), 4)


def moving_average_slope(bars: list[PriceBar], window: int, lookback: int = 5) -> float | None:
    """window일 이동평균이 lookback거래일 전 대비 어느 방향으로 얼마나 움직였는지."""
    if len(bars) < window + lookback:
        return None
    current = moving_average(bars, window)
    prior = moving_average(bars[:-lookback], window)
    if current is None or prior is None:
        return None
    return round(current - prior, 4)


def pct_below_52w_high(bars: list[PriceBar]) -> float | None:
    if not bars:
        return None
    window = bars[-252:] if len(bars) > 252 else bars
    high = max(b.high for b in window)
    if high <= 0:
        return None
    return round((bars[-1].close - high) / high * 100.0, 2)


def _period_return_pct(bars: list[PriceBar], window: int) -> float | None:
    if len(bars) <= window:
        return None
    start = bars[-1 - window].close
    end = bars[-1].close
    if start <= 0:
        return None
    return round((end - start) / start * 100.0, 2)


def relative_strength(
    bars: list[PriceBar], benchmark_bars: list[PriceBar], window: int
) -> float | None:
    """종목의 window거래일 수익률에서 벤치마크의 같은 기간 수익률을 뺀 값. 업종/시장 대비
    상대수익률 계산에 공용으로 쓴다(호출부가 벤치마크를 업종지수/시장지수 어느 쪽으로 넘기든
    동일)."""
    ticker_return = _period_return_pct(bars, window)
    benchmark_return = _period_return_pct(benchmark_bars, window)
    if ticker_return is None or benchmark_return is None:
        return None
    return round(ticker_return - benchmark_return, 2)


def volume_change_ratio(bars: list[PriceBar], window: int = 20) -> float | None:
    if len(bars) < window + 1:
        return None
    avg_volume = statistics.fmean(b.volume for b in bars[-window - 1 : -1])
    if avg_volume <= 0:
        return None
    return round(bars[-1].volume / avg_volume, 3)


def volatility(bars: list[PriceBar], window: int = 20) -> float | None:
    if len(bars) < window + 1:
        return None
    window_bars = bars[-window - 1 :]
    returns = [
        (window_bars[i].close - window_bars[i - 1].close) / window_bars[i - 1].close
        for i in range(1, len(window_bars))
        if window_bars[i - 1].close > 0
    ]
    if len(returns) < 2:
        return None
    return round(statistics.stdev(returns) * 100.0, 3)


def max_drawdown(bars: list[PriceBar], window_days: int = 365) -> float | None:
    if not bars:
        return None
    window = bars[-window_days:] if len(bars) > window_days else bars
    peak = window[0].close
    worst = 0.0
    for bar in window:
        peak = max(peak, bar.close)
        if peak > 0:
            worst = min(worst, (bar.close - peak) / peak)
    return round(worst * 100.0, 2)


class PriceSupplyDemandMetrics(BaseModel):
    as_of: date
    close: float
    ma20: float | None
    ma60: float | None
    ma120: float | None
    ma200: float | None
    ma20_slope_5d: float | None
    pct_below_52w_high: float | None
    return_5d: float | None
    return_20d: float | None
    rs_20d_vs_benchmark: float | None
    rs_60d_vs_benchmark: float | None
    volume_change_ratio_20d: float | None
    volatility_20d_pct: float | None
    max_drawdown_1y_pct: float | None


def compute_price_supply_demand_metrics(
    bars: list[PriceBar], benchmark_bars: list[PriceBar]
) -> PriceSupplyDemandMetrics | None:
    if not bars:
        return None
    return PriceSupplyDemandMetrics(
        as_of=bars[-1].date,
        close=bars[-1].close,
        ma20=moving_average(bars, 20),
        ma60=moving_average(bars, 60),
        ma120=moving_average(bars, 120),
        ma200=moving_average(bars, 200),
        ma20_slope_5d=moving_average_slope(bars, 20, lookback=5),
        pct_below_52w_high=pct_below_52w_high(bars),
        return_5d=_period_return_pct(bars, 5),
        return_20d=_period_return_pct(bars, 20),
        rs_20d_vs_benchmark=relative_strength(bars, benchmark_bars, 20),
        rs_60d_vs_benchmark=relative_strength(bars, benchmark_bars, 60),
        volume_change_ratio_20d=volume_change_ratio(bars),
        volatility_20d_pct=volatility(bars),
        max_drawdown_1y_pct=max_drawdown(bars),
    )


def price_supply_demand_score(m: PriceSupplyDemandMetrics) -> float | None:
    """섹션 11 가격/수급 카테고리 점수 (0-100). 200일선 대비 위치, 20일 상대강도, 52주 고점
    대비 낙폭 3가지를 동일 가중치로 결합한다 - 누락된 구성요소는 제외하고 나머지로 평균한다."""
    components: list[float] = []
    if m.ma200 is not None and m.ma200 > 0:
        components.append(_linear_map((m.close - m.ma200) / m.ma200 * 100.0, -20.0, 20.0))
    if m.rs_20d_vs_benchmark is not None:
        components.append(_linear_map(m.rs_20d_vs_benchmark, -15.0, 15.0))
    if m.pct_below_52w_high is not None:
        components.append(_linear_map(m.pct_below_52w_high, -50.0, 0.0))
    if not components:
        return None
    return round(sum(components) / len(components), 1)


def build_price_supply_demand_rationale(
    m: PriceSupplyDemandMetrics, ticker: str
) -> tuple[str, list[Citation]]:
    """가격/거래량 자체가 근거라 별도 문서 출처가 없다 - Yahoo Finance 가격 히스토리
    수치를 그대로 요약해서 보여준다(결정론적, LLM 호출 없음)."""
    lines = [f"- 종가 {m.close:,.0f} (기준일 {m.as_of.isoformat()})"]
    if m.ma200 is not None:
        position = "위" if m.close >= m.ma200 else "아래"
        lines.append(f"- 200일 이동평균({m.ma200:,.0f}) {position}에 위치")
    if m.rs_20d_vs_benchmark is not None:
        lines.append(f"- 20거래일 벤치마크 대비 상대수익률 {m.rs_20d_vs_benchmark:+.2f}%p")
    if m.pct_below_52w_high is not None:
        lines.append(f"- 52주 고점 대비 {m.pct_below_52w_high:.2f}%")
    citation = Citation(label="Yahoo Finance", url=f"https://finance.yahoo.com/quote/{ticker}")
    return "\n".join(lines[:5]), [citation]


def classify_price_reaction(
    news_direction: Direction, price_return_around_event_pct: float, threshold_pct: float = 2.0
) -> PriceReactionPattern:
    """섹션 11 패턴 매칭. 재료 방향과 사건 전후 가격 반응을 함께 봐서 "예상보다 강한/약한
    반응"을 구분한다 - 단순히 감성이 긍정적이면 상승 점수를 주는 방식이 아니다."""
    if news_direction == Direction.NEUTRAL:
        return PriceReactionPattern.NEUTRAL
    moved_up = price_return_around_event_pct >= threshold_pct
    moved_down = price_return_around_event_pct <= -threshold_pct
    if news_direction == Direction.BULLISH:
        if moved_up:
            return PriceReactionPattern.POSITIVE_NEWS_PRICE_UP
        if moved_down:
            return PriceReactionPattern.POSITIVE_NEWS_PRICE_DOWN
        return PriceReactionPattern.NEUTRAL
    if moved_down:
        return PriceReactionPattern.NEGATIVE_NEWS_PRICE_DOWN
    if not moved_down:
        return PriceReactionPattern.NEGATIVE_NEWS_PRICE_FLAT_OR_UP
    return PriceReactionPattern.NEUTRAL

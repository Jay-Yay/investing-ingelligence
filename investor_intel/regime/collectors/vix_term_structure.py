from __future__ import annotations

from datetime import datetime

from investor_intel.market_data.yfinance_adapter import YahooFinanceAdapter
from investor_intel.regime.collectors.common import build_observation, unavailable_observation
from investor_intel.regime.models import IndicatorFrequency, IndicatorId, IndicatorObservation
from investor_intel.regime.percentile import percentile_rank

_VIX_SYMBOL = "^VIX"
_VIX3M_SYMBOL = "^VIX3M"
INDICATOR_NAME = "VIX 기간구조"
SOURCE_NAME = "Yahoo Finance (Cboe VIX/VIX3M)"
_SOURCE_URL = "https://finance.yahoo.com/quote/%5EVIX"


def collect(yahoo: YahooFinanceAdapter, fetched_at: datetime) -> IndicatorObservation:
    """VIX/VIX3M 비율(콘탱고 <1 / 백워데이션 >=1)을 헤드라인 값으로 쓴다.

    details 키: vix_level, vix3m_level, vix_1y_percentile, vix_5y_percentile,
    backwardation_signal, contango_calm_signal. VIX 선물 1월물/2월물 데이터는 무료 소스가
    없어 이번 페이즈에서는 다루지 않는다(details에 없음 - 임의로 채우지 않는다).
    """
    try:
        vix_history = yahoo.get_price_history(_VIX_SYMBOL, days=365 * 5)
        vix3m_history = yahoo.get_price_history(_VIX3M_SYMBOL, days=30)
    except Exception as exc:  # noqa: BLE001
        return unavailable(fetched_at, str(exc))

    if not vix_history or not vix3m_history:
        return unavailable(fetched_at, "Yahoo Finance returned no VIX/VIX3M data")

    vix_bar = vix_history[-1]
    vix3m_bar = vix3m_history[-1]
    vix_level = vix_bar.close
    vix3m_level = vix3m_bar.close
    ratio = round(vix_level / vix3m_level, 3) if vix3m_level else None

    closes_1y = [b.close for b in vix_history if (vix_bar.date - b.date).days <= 365]
    closes_5y = [b.close for b in vix_history]
    percentile_1y = percentile_rank(closes_1y, vix_level)
    percentile_5y = percentile_rank(closes_5y, vix_level)

    backwardation_signal = bool(ratio is not None and ratio >= 1.0)
    contango_calm_signal = bool(
        ratio is not None and ratio < 0.9 and percentile_5y is not None and percentile_5y <= 10
    )

    return build_observation(
        indicator_id=IndicatorId.VIX_TERM_STRUCTURE,
        indicator_name=INDICATOR_NAME,
        value=ratio,
        unit="ratio",
        observation_date=vix_bar.date,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=_SOURCE_URL,
        frequency=IndicatorFrequency.DAILY,
        details={
            "vix_level": vix_level,
            "vix3m_level": vix3m_level,
            "vix_1y_percentile": percentile_1y,
            "vix_5y_percentile": percentile_5y,
            "backwardation_signal": backwardation_signal,
            "contango_calm_signal": contango_calm_signal,
        },
    )


def unavailable(fetched_at: datetime, reason: str) -> IndicatorObservation:
    return unavailable_observation(
        indicator_id=IndicatorId.VIX_TERM_STRUCTURE,
        indicator_name=INDICATOR_NAME,
        unit="ratio",
        frequency=IndicatorFrequency.DAILY,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=_SOURCE_URL,
        reason=reason,
    )

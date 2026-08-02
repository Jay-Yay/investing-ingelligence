from __future__ import annotations

from datetime import date, datetime, timedelta

from investor_intel.regime.collectors.common import build_observation, unavailable_observation
from investor_intel.regime.fred_client import FredClient, series_url
from investor_intel.regime.models import IndicatorFrequency, IndicatorId, IndicatorObservation

_ICSA = "ICSA"  # 신규 실업수당 청구
_IC4WSA = "IC4WSA"  # 신규 청구 4주 평균
_CCSA = "CCSA"  # 계속 실업수당 청구
_SAHM = "SAHMREALTIME"  # Sahm Rule
INDICATOR_NAME = "고용 냉각 복합지표"
SOURCE_NAME = "FRED (Federal Reserve Bank of St. Louis)"
_BACKFILL_START = date(1990, 1, 1)
_SAHM_APPROACHING_THRESHOLD = 0.35
_SAHM_EXCEEDED_THRESHOLD = 0.5


def _nearest_value(
    series: list[tuple[date, float]], target_date: date, tolerance_days: int = 10
) -> float | None:
    candidates = [
        (abs((d - target_date).days), v)
        for d, v in series
        if abs((d - target_date).days) <= tolerance_days
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p[0])
    return candidates[0][1]


def _fetch_series(fred: FredClient, series_id: str) -> list[tuple[date, float]]:
    raw = fred.get_observations(series_id, observation_start=_BACKFILL_START)
    return sorted((o.observation_date, o.value) for o in raw if o.value is not None)


def _yoy_change_pct(series: list[tuple[date, float]]) -> float | None:
    if not series:
        return None
    latest_date, latest_value = series[-1]
    year_ago_date = date(latest_date.year - 1, latest_date.month, latest_date.day)
    year_ago = _nearest_value(series, year_ago_date)
    if year_ago is None or year_ago == 0:
        return None
    return round((latest_value - year_ago) / year_ago * 100, 1)


def collect(fred: FredClient, fetched_at: datetime) -> IndicatorObservation:
    """ICSA(신규 청구)/IC4WSA(4주 평균)/CCSA(계속 청구)/SAHMREALTIME(Sahm Rule) 4개 FRED
    시리즈를 조합한 복합지표. value는 4주 평균 신규청구의 전년 동기 대비 변화율(%) - 단일
    헤드라인 숫자로 쓰기 위함이며, 나머지는 details에 함께 담는다. Sahm Rule은 후행성이 커서
    단독 신호로 쓰지 않는다는 지침에 따라 cooling_signal 산출에 반드시 다른 지표와 함께
    반영한다.

    details 키: initial_claims_4wma, initial_claims_4wma_yoy_pct, continued_claims,
    continued_claims_yoy_pct, sahm_rule_level, sahm_rule_change_3m, cooling_signal,
    sahm_approaching_signal, sahm_exceeded_signal.
    """
    try:
        icsa = _fetch_series(fred, _ICSA)
        ic4wsa = _fetch_series(fred, _IC4WSA)
        ccsa = _fetch_series(fred, _CCSA)
        sahm = _fetch_series(fred, _SAHM)
    except Exception as exc:  # noqa: BLE001
        return unavailable(fetched_at, str(exc))

    del icsa  # 4주 평균(IC4WSA)이 노이즈가 적어 헤드라인으로 쓰고, 주간 원계열은 참고용으로만 fetch

    if not ic4wsa:
        return unavailable(fetched_at, "FRED returned no usable IC4WSA observations")

    latest_date, latest_4wma = ic4wsa[-1]
    claims_4wma_yoy = _yoy_change_pct(ic4wsa)
    continued_claims_yoy = _yoy_change_pct(ccsa)
    sahm_level = sahm[-1][1] if sahm else None
    sahm_change_3m = None
    if sahm and sahm_level is not None:
        sahm_3m_ago = _nearest_value(sahm, latest_date - timedelta(days=90))
        if sahm_3m_ago is not None:
            sahm_change_3m = round(sahm_level - sahm_3m_ago, 2)

    sahm_approaching_signal = bool(
        sahm_level is not None and sahm_level >= _SAHM_APPROACHING_THRESHOLD
    )
    sahm_exceeded_signal = bool(sahm_level is not None and sahm_level >= _SAHM_EXCEEDED_THRESHOLD)
    claims_cooling = (
        claims_4wma_yoy is not None
        and claims_4wma_yoy >= 15
        and continued_claims_yoy is not None
        and continued_claims_yoy > 0
    )
    cooling_signal = bool(claims_cooling or sahm_exceeded_signal)

    return build_observation(
        indicator_id=IndicatorId.EMPLOYMENT_COOLING,
        indicator_name=INDICATOR_NAME,
        value=claims_4wma_yoy,
        unit="pct_yoy",
        observation_date=latest_date,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=series_url(_IC4WSA),
        frequency=IndicatorFrequency.WEEKLY,
        details={
            "initial_claims_4wma": latest_4wma,
            "initial_claims_4wma_yoy_pct": claims_4wma_yoy,
            "continued_claims": ccsa[-1][1] if ccsa else None,
            "continued_claims_yoy_pct": continued_claims_yoy,
            "sahm_rule_level": sahm_level,
            "sahm_rule_change_3m": sahm_change_3m,
            "cooling_signal": cooling_signal,
            "sahm_approaching_signal": sahm_approaching_signal,
            "sahm_exceeded_signal": sahm_exceeded_signal,
        },
    )


def unavailable(fetched_at: datetime, reason: str) -> IndicatorObservation:
    return unavailable_observation(
        indicator_id=IndicatorId.EMPLOYMENT_COOLING,
        indicator_name=INDICATOR_NAME,
        unit="pct_yoy",
        frequency=IndicatorFrequency.WEEKLY,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=series_url(_IC4WSA),
        reason=reason,
    )

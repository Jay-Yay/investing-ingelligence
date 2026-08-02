from __future__ import annotations

from investor_intel.regime.models import (
    IndicatorId,
    IndicatorObservation,
    IndicatorStatus,
    RegimeSignal,
    SignalDirection,
    SignalStatus,
)

# 지표별로 details에서 확인하는 신호 키 -> (방향, 심각도 0-100). 각 collector 모듈이 실제로
# 채우는 details 키와 정확히 일치해야 한다(각 collector docstring 참고).
_SIGNAL_KEYS: dict[IndicatorId, list[tuple[str, SignalDirection, int]]] = {
    IndicatorId.CREDIT_SPREAD_HY_OAS: [
        ("cooling_signal", SignalDirection.COOLING, 75),
        ("overheating_signal", SignalDirection.OVERHEATING, 60),
    ],
    IndicatorId.CHICAGO_FED_ANFCI: [
        ("tightening_signal", SignalDirection.COOLING, 60),
        ("easing_signal", SignalDirection.IMPROVING, 40),
    ],
    IndicatorId.YIELD_CURVE_10Y3M: [
        ("rapid_normalization_signal", SignalDirection.COOLING, 65),
    ],
    IndicatorId.EMPLOYMENT_COOLING: [
        ("sahm_exceeded_signal", SignalDirection.COOLING, 85),
        ("cooling_signal", SignalDirection.COOLING, 75),
    ],
    IndicatorId.VIX_TERM_STRUCTURE: [
        ("backwardation_signal", SignalDirection.COOLING, 70),
        ("contango_calm_signal", SignalDirection.OVERHEATING, 55),
    ],
    IndicatorId.MARKET_BREADTH: [
        ("cooling_signal", SignalDirection.COOLING, 70),
        ("narrow_leadership_signal", SignalDirection.OVERHEATING, 55),
    ],
    IndicatorId.LEVERAGE_POSITIONING: [
        ("overheating_signal", SignalDirection.OVERHEATING, 75),
        ("deleveraging_signal", SignalDirection.COOLING, 60),
    ],
}


def build_signal(
    obs: IndicatorObservation,
    previous_obs: IndicatorObservation | None,
) -> RegimeSignal:
    """지표 하나의 오늘 상태를 신호로 변환한다.

    daily 지표는 "최소 2거래일 연속 조건 충족 시 confirmed", weekly/monthly 지표는 "직전
    발표 대비 방향이 확인되면 confirmed"라는 스펙 규칙을, 둘 다 "어제 저장된 processed
    스냅샷에서도 같은 신호가 켜져 있었는가"로 통일해서 구현한다 - weekly/monthly는 우리가
    매일 실행해도 실제 발표가 갱신되지 않는 날에는 어제와 오늘의 observation_date가 같으므로
    "직전 발표"와 "어제 스냅샷"이 사실상 같은 값을 가리켜 근사가 성립한다. 처음 켜진 신호는
    watch로, 하루 전에도 켜져 있었다면 confirmed로 승격한다.
    """
    if obs.status == IndicatorStatus.UNAVAILABLE:
        return RegimeSignal(
            indicator_id=obs.indicator_id,
            status=SignalStatus.UNAVAILABLE,
            direction=SignalDirection.NEUTRAL,
            severity=0,
            reason=str(obs.details.get("error_reason", "데이터 없음")),
            observation_date=None,
            data_age_days=None,
        )

    fired = [
        (key, direction, severity)
        for key, direction, severity in _SIGNAL_KEYS.get(obs.indicator_id, [])
        if obs.details.get(key)
    ]
    if not fired:
        status = SignalStatus.NORMAL
        if previous_obs is not None and previous_obs.status != IndicatorStatus.UNAVAILABLE:
            prev_had_signal = any(
                previous_obs.details.get(key)
                for key, _, _ in _SIGNAL_KEYS.get(obs.indicator_id, [])
            )
            if prev_had_signal:
                status = SignalStatus.RESOLVED
        return RegimeSignal(
            indicator_id=obs.indicator_id,
            status=status,
            direction=SignalDirection.NEUTRAL,
            severity=0,
            reason="정상 범위",
            observation_date=obs.observation_date,
            data_age_days=obs.data_age_days,
        )

    key, direction, severity = max(fired, key=lambda t: t[2])
    prev_fired = bool(
        previous_obs is not None
        and previous_obs.status != IndicatorStatus.UNAVAILABLE
        and previous_obs.details.get(key)
    )
    status = SignalStatus.CONFIRMED if prev_fired else SignalStatus.WATCH

    return RegimeSignal(
        indicator_id=obs.indicator_id,
        status=status,
        direction=direction,
        severity=severity,
        reason=key,
        observation_date=obs.observation_date,
        data_age_days=obs.data_age_days,
    )


def build_signals(
    observations: dict[IndicatorId, IndicatorObservation],
    previous_observations: dict[IndicatorId, IndicatorObservation] | None,
) -> list[RegimeSignal]:
    previous_observations = previous_observations or {}
    return [
        build_signal(obs, previous_observations.get(indicator_id))
        for indicator_id, obs in observations.items()
    ]

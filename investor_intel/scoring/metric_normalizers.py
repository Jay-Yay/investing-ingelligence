from __future__ import annotations

from investor_intel.models.config import MetricSpec
from investor_intel.scoring.models import Feature

_TREND_SCORES = {"개선": 85.0, "횡보": 50.0, "악화": 15.0}


def _linear_map(value: float, bad: float, good: float) -> float:
    """bad->0, good->100으로 선형 매핑 후 0-100 클램프. bad/good의 대소관계는 호출부(kind별
    의미)에 따라 달라질 수 있다(예: inverse류는 good이 bad보다 작은 값)."""
    if good == bad:
        return 50.0
    ratio = (value - bad) / (good - bad)
    return round(max(0.0, min(100.0, ratio * 100.0)), 1)


def normalize_feature(feature: Feature, spec: MetricSpec) -> float | None:
    """metric_specs 설정 하나를 근거로 feature 값을 0-100 점수로 변환한다.

    반환값이 None이면 이 feature는 정규화 불가(값 없음, 알 수 없는 kind 등)로 취급되고 호출부가
    missing으로 처리한다 - 임의의 기본값을 만들지 않는다.
    """
    kind = spec.kind

    if kind == "qualitative_trend":
        trend = feature.details.get("trend")
        return _TREND_SCORES.get(trend) if trend else None

    if feature.value is None:
        return None

    if kind == "growth_rate_pct":
        assert spec.bad is not None and spec.good is not None
        return _linear_map(feature.value, spec.bad, spec.good)

    if kind == "inverse_growth_rate_pct":
        # bad(=높은 증가율)가 0점, good(=낮은 증가율)이 100점 - _linear_map(value, bad, good)에
        # bad>good을 그대로 넘기면 방향이 자동으로 뒤집힌다.
        assert spec.bad is not None and spec.good is not None
        return _linear_map(feature.value, spec.bad, spec.good)

    if kind == "percent_passthrough":
        # 0-1 스케일로 온 값(예: 0.62)과 0-100 스케일로 온 값(62) 둘 다 지원한다.
        value = feature.value * 100.0 if -1.0 <= feature.value <= 1.0 else feature.value
        return round(max(0.0, min(100.0, value)), 1)

    if kind == "boolean":
        return 100.0 if feature.value >= 1.0 else 0.0

    if kind == "inverse_months":
        # good(짧은 개월수)이 100점, bad(긴 개월수)가 0점 - 값이 낮을수록 좋은 지표(재고월수 등).
        assert spec.bad is not None and spec.good is not None
        return _linear_map(feature.value, spec.bad, spec.good)

    return None

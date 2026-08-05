from __future__ import annotations

from datetime import date

from investor_intel.regime.percentile import (  # noqa: F401 - re-exported for scoring callers
    change_series,
    compute_changes,
    compute_percentiles,
    percentile_rank,
    value_n_observations_back,
    values_within_window,
    zscore,
)
from investor_intel.scoring.models import Feature

_SOCIAL_OR_RUMOR_EXCLUDED_REASON = (
    "5순위 출처(소셜미디어/루머)이거나 fact_type=rumor - 복수의 신뢰 가능한 출처로 확인되기 "
    "전까지 점수에 직접 반영하지 않는다 (섹션 5)"
)


def is_score_eligible(feature: Feature) -> tuple[bool, str]:
    """이 feature를 점수 계산에 직접 반영해도 되는지. False면 (사유)와 함께 반환한다.

    소셜미디어 출처이거나 fact_type이 rumor인 feature는 이 저장소가 아직 "복수 출처 교차 확인"
    로직을 갖고 있지 않으므로 보수적으로 항상 제외한다 - 리포트에는 "확인 필요" 신호로만
    노출한다(evaluation/report 계층 몫).
    """
    from investor_intel.scoring.models import FactType, SourceTier

    if feature.source_tier == SourceTier.SOCIAL or feature.fact_type == FactType.RUMOR:
        return False, _SOCIAL_OR_RUMOR_EXCLUDED_REASON
    return True, ""


def is_stale(feature: Feature, as_of: date) -> bool:
    if feature.max_age_days is None:
        return False
    return (as_of - feature.published_at.date()).days > feature.max_age_days


def latest_features_by_metric(features: list[Feature]) -> dict[str, Feature]:
    """같은 metric에 대해 복수 출처/시점이 있으면 published_at이 가장 최근인 것을 채택한다."""
    resolved: dict[str, Feature] = {}
    for feature in features:
        current = resolved.get(feature.metric)
        if current is None or feature.published_at > current.published_at:
            resolved[feature.metric] = feature
    return resolved

from __future__ import annotations

from datetime import date

from investor_intel.models.config import MetricSpec
from investor_intel.scoring.metric_normalizers import normalize_feature
from investor_intel.scoring.models import CategoryScore, Citation, Feature
from investor_intel.scoring.normalization import is_score_eligible, is_stale

_MAX_RATIONALE_LINES = 5


def _feature_rationale_line(metric_id: str, feature: Feature) -> str:
    value_text = (
        feature.details.get("trend", "N/A")
        if feature.value is None
        else f"{feature.value:g}{feature.unit}"
    )
    return (
        f"- {metric_id}: {value_text} ({feature.period}, "
        f"[{feature.source_name}]({feature.source_url}))"
    )


def _build_rationale(
    contributing_features: list[tuple[str, Feature]],
) -> tuple[str, list[Citation]]:
    """기여한 feature들을 근거 문단(3-5줄)과 출처 목록으로 요약한다. LLM 호출 없이 이미
    Feature에 있는 metric/값/기간/출처만 그대로 나열하는 결정론적 생성 방식이다."""
    lines = [_feature_rationale_line(metric_id, f) for metric_id, f in contributing_features]
    citations: list[Citation] = []
    seen_urls: set[str] = set()
    for _, f in contributing_features:
        if f.source_url in seen_urls:
            continue
        seen_urls.add(f.source_url)
        citations.append(Citation(label=f.source_name, url=f.source_url))
    return "\n".join(lines[:_MAX_RATIONALE_LINES]), citations


def compute_category_score(
    category: str,
    metric_ids: list[str],
    features_by_metric: dict[str, Feature],
    metric_specs: dict[str, MetricSpec],
    weight: float,
    as_of: date,
) -> CategoryScore:
    """한 카테고리 안의 metric들을 동일 가중치로 평균한다 (regime/scoring.py의 "누락 지표를
    0점 처리하지 않고 가용 가중치를 비례 재조정" 원칙을 종목 스코어링에도 그대로 적용).

    metric_ids가 비어 있으면(예: earnings_outlook/valuation처럼 별도 모듈이 직접 점수를 넣는
    카테고리) 이 함수는 호출되지 않고 파이프라인이 그 모듈의 결과를 CategoryScore로 직접
    감싼다.
    """
    if not metric_ids:
        return CategoryScore(
            category=category, score=None, coverage=0.0, weight=weight, contributing_features=0
        )

    total = len(metric_ids)
    contributing = 0
    score_sum = 0.0
    missing: list[str] = []
    contributing_features: list[tuple[str, Feature]] = []

    for metric_id in metric_ids:
        feature = features_by_metric.get(metric_id)
        spec = metric_specs.get(metric_id)
        if feature is None or spec is None:
            missing.append(metric_id)
            continue
        eligible, _reason = is_score_eligible(feature)
        if not eligible or is_stale(feature, as_of):
            missing.append(metric_id)
            continue
        contribution = normalize_feature(feature, spec)
        if contribution is None:
            missing.append(metric_id)
            continue
        score_sum += contribution
        contributing += 1
        contributing_features.append((metric_id, feature))

    if contributing == 0:
        return CategoryScore(
            category=category,
            score=None,
            coverage=0.0,
            weight=weight,
            contributing_features=0,
            missing_metrics=missing,
        )

    rationale, citations = _build_rationale(contributing_features)
    return CategoryScore(
        rationale=rationale,
        citations=citations,
        category=category,
        score=round(score_sum / contributing, 1),
        coverage=round(contributing / total, 3),
        weight=weight,
        contributing_features=contributing,
        missing_metrics=missing,
    )


def compute_total_score(category_scores: list[CategoryScore]) -> tuple[float | None, float]:
    """대분류 점수들을 설정된 weight로 가중평균해 총점을 낸다.

    반환: (총점 0-100 또는 계산 불가 시 None, 전체 커버리지 0-1). 카테고리 점수가 None인
    항목은(예: 데이터가 아예 없는 카테고리) 가중치를 재조정해서 제외한다 - 0점 처리하지 않는다.
    """
    total_weight = sum(c.weight for c in category_scores)
    available_weight = 0.0
    weighted_sum = 0.0
    for c in category_scores:
        if c.score is None:
            continue
        available_weight += c.weight
        weighted_sum += c.weight * c.score
    if available_weight == 0 or total_weight == 0:
        return None, 0.0
    return round(weighted_sum / available_weight, 1), round(available_weight / total_weight, 3)

from __future__ import annotations

from investor_intel.models.common import ConfidenceLevel
from investor_intel.models.config import ConfidenceConfig
from investor_intel.scoring.models import Feature, SourceTier


def compute_confidence(
    total_coverage: float,
    contributing_features: list[Feature],
    missing_critical_count: int,
    config: ConfidenceConfig,
) -> tuple[float, ConfidenceLevel]:
    """섹션 12 신뢰도 계산.

    실제로 점수에 기여한 feature들의 출처 등급 구성과 전체 커버리지를 절반씩 반영하고, 핵심
    데이터 누락 개수만큼 감점한다. 과거 소스 정확도/컨센서스 분산/feature 간 방향 일치도는 이
    구현의 범위 밖이다 - 평가(evaluation) 이력이 충분히 쌓이기 전까지는 계산할 근거 자체가
    없으므로 임의로 채우지 않는다(README "알려진 한계" 참고).
    """
    if total_coverage <= 0.0 and not contributing_features:
        return 0.0, ConfidenceLevel.LOW

    if contributing_features:
        official_like = sum(
            1
            for f in contributing_features
            if f.source_tier in (SourceTier.OFFICIAL, SourceTier.INDUSTRY)
        )
        broker_like = sum(1 for f in contributing_features if f.source_tier == SourceTier.BROKER)
        tier_ratio = (official_like + 0.6 * broker_like) / len(contributing_features)
    else:
        # price_supply_demand/macro_liquidity/normalized_valuation처럼 전용 모듈이 직접 점수를
        # 계산하는 카테고리만 기여했을 때는 개별 feature의 출처 등급 정보가 없다 - 이 경우
        # tier_ratio를 0으로 깔아뭉개지 않고 중립값(0.5)을 쓴다. 실제 출처 신뢰도는 각 전용
        # 모듈이 이미 신뢰할 수 있는 소스(거래소 가격, regime 지표 등)만 쓰도록 설계돼 있다.
        tier_ratio = 0.5

    base = 0.5 * total_coverage + 0.5 * tier_ratio
    # coverage(카테고리별 가중치 재조정)가 이미 "얼마나 많은 metric이 비었는지"를 반영하므로,
    # 여기서는 그 위에 소폭의 추가 감점만 둔다 - 넓은 metric 목록(예: 메모리 섹터 47개)에서는
    # 개별 결측 개수가 쉽게 두 자릿수가 되므로, 무제한 선형 감점을 두면 coverage와 이중으로
    # 벌점을 줘 confidence가 근거 없이 0으로 바닥나는 문제가 생긴다. 최대 감점은 0.20으로 캡핑한다.
    penalty = min(0.20, config.stale_penalty_per_feature * missing_critical_count)
    confidence = round(max(0.0, min(1.0, base - penalty)), 3)

    if confidence < config.low_threshold:
        level = ConfidenceLevel.LOW
    elif confidence >= config.high_threshold:
        level = ConfidenceLevel.HIGH
    else:
        level = ConfidenceLevel.MEDIUM
    return confidence, level

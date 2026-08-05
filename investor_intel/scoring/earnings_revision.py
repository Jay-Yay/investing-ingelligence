from __future__ import annotations

from pydantic import BaseModel

from investor_intel.scoring.metric_normalizers import _linear_map


class EarningsRevisionInputs(BaseModel):
    """섹션 9. 목표주가는 의도적으로 포함하지 않는다 - "목표주가는 직접적인 매수 점수로 사용하지
    않는다"는 원칙을 타입 수준에서 강제한다. 값은 국내 IB 리포트에서 LLM으로 추출한 프록시
    수치다(`llm/ib_metrics_extraction.py`) - 유료 I/B/E/S 데이터 없이 얻을 수 있는 근사치이며,
    실제 컨센서스 패널 데이터보다 표본이 작고 노이즈가 있다는 한계가 있다."""

    ticker: str
    eps_revision_1m_pct: float | None = None
    eps_revision_3m_pct: float | None = None
    eps_revision_6m_pct: float | None = None
    analysts_upgraded: int | None = None
    analysts_downgraded: int | None = None
    guidance_or_earnings_surprise_pct: float | None = None
    next_quarter_estimate_change_pct: float | None = None
    this_year_estimate_change_pct: float | None = None
    next_year_estimate_change_pct: float | None = None


class EarningsRevisionWeights(BaseModel):
    """기본값은 섹션 9의 공식을 그대로 옮긴 것 (40/25/20/15%). 설정 파일로 바꾸고 싶으면
    호출부에서 다른 값을 넘긴다 - 이 저장소는 아직 이 가중치를 위한 별도 YAML을 두지 않았다
    (필요해지면 global_scoring.yaml에 섹션을 추가한다)."""

    eps_revision_1m: float = 0.40
    eps_revision_3m: float = 0.25
    analyst_upgrade_ratio: float = 0.20
    guidance_and_surprise: float = 0.15


_DEFAULT_WEIGHTS = EarningsRevisionWeights()


def compute_earnings_revision_score(
    inputs: EarningsRevisionInputs,
    weights: EarningsRevisionWeights = _DEFAULT_WEIGHTS,
) -> tuple[float | None, float]:
    """반환: (0-100 점수 또는 데이터 없으면 None, 사용된 가중치 비중 0-1).

    누락된 구성요소는 0점 처리하지 않고 가용 가중치를 재조정한다 - 다른 카테고리 스코어링과
    동일한 원칙.
    """
    components: list[tuple[float, float]] = []

    if inputs.eps_revision_1m_pct is not None:
        components.append(
            (weights.eps_revision_1m, _linear_map(inputs.eps_revision_1m_pct, -10.0, 10.0))
        )
    if inputs.eps_revision_3m_pct is not None:
        components.append(
            (weights.eps_revision_3m, _linear_map(inputs.eps_revision_3m_pct, -15.0, 15.0))
        )

    upgrade_ratio_pct: float | None = None
    if inputs.analysts_upgraded is not None and inputs.analysts_downgraded is not None:
        total = inputs.analysts_upgraded + inputs.analysts_downgraded
        if total > 0:
            upgrade_ratio_pct = inputs.analysts_upgraded / total * 100.0
    if upgrade_ratio_pct is not None:
        components.append((weights.analyst_upgrade_ratio, upgrade_ratio_pct))

    if inputs.guidance_or_earnings_surprise_pct is not None:
        components.append(
            (
                weights.guidance_and_surprise,
                _linear_map(inputs.guidance_or_earnings_surprise_pct, -20.0, 20.0),
            )
        )

    total_weight = sum(w for w, _ in components)
    if total_weight == 0:
        return None, 0.0

    score = sum(w * s for w, s in components) / total_weight
    max_weight = (
        weights.eps_revision_1m
        + weights.eps_revision_3m
        + weights.analyst_upgrade_ratio
        + weights.guidance_and_surprise
    )
    coverage = round(total_weight / max_weight, 3) if max_weight else 0.0
    return round(score, 1), coverage


def build_earnings_revision_rationale(inputs: EarningsRevisionInputs) -> str:
    """국내 IB 리포트에서 추출된 어떤 하위 지표가 이번 점수에 반영됐는지 나열한다.
    EarningsRevisionInputs가 아직 개별 문서 출처 URL을 담지 않아(README "알려진 한계")
    citation은 만들지 않는다 - 링크가 필요하면 EarningsRevisionInputs에 source_url을
    추가하는 것이 다음 단계."""
    lines: list[str] = []
    if inputs.eps_revision_1m_pct is not None:
        lines.append(f"- 1개월 EPS 수정률: {inputs.eps_revision_1m_pct:+.1f}%")
    if inputs.eps_revision_3m_pct is not None:
        lines.append(f"- 3개월 EPS 수정률: {inputs.eps_revision_3m_pct:+.1f}%")
    if inputs.analysts_upgraded is not None and inputs.analysts_downgraded is not None:
        lines.append(
            f"- 애널리스트 상향/하향: {inputs.analysts_upgraded}건 상향 / "
            f"{inputs.analysts_downgraded}건 하향"
        )
    if inputs.guidance_or_earnings_surprise_pct is not None:
        lines.append(f"- 가이던스/실적 서프라이즈: {inputs.guidance_or_earnings_surprise_pct:+.1f}%")
    return "\n".join(lines[:5])

from __future__ import annotations

from datetime import date

from jinja2 import Template
from pydantic import BaseModel

from investor_intel.portfolio.guardrails import GuardrailViolation

_TEMPLATE = Template(
    """# Daily Investment Brief — {{ report_date.isoformat() }}

{{ narrative }}

## 포트폴리오 신호

{% if position_signals %}
| 종목 | 신호 | 강도 | 투자가설 변화 | 핵심 근거 | 반대 근거 | 다음 확인 조건 |
| --- | --- | ---: | --- | --- | --- | --- |
{% for row in position_signals -%}
| {{ row.symbol }} | {{ row.signal or "판단 보류" }} | {{ row.signal_strength }} | {{ row.thesis_shift }} | {{ (row.new_facts or ["-"]) | join("; ") }} | {{ (row.counter_evidence or ["-"]) | join("; ") }} | {{ row.next_check_conditions or "-" }} |
{% endfor %}
{%- else %}
오늘 새로 판단된 보유 종목 신호 없음.
{%- endif %}

## 신규 후보

{% set candidate_rows = tenbagger_candidates | selectattr("tier", "equalto", "candidate") | list %}
{% set watchlist_rows = tenbagger_candidates | selectattr("tier", "equalto", "watchlist") | list %}
{% if candidate_rows %}
| 종목 | 총점 | 10배 경로 | 최대 리스크 |
| --- | ---: | --- | --- |
{% for row in candidate_rows -%}
| {{ row.symbol_or_company }} | {{ row.total_score }} | {{ row.ten_bagger_path }} | {{ row.biggest_risk }} |
{% endfor %}
{%- else %}
오늘 정식 후보(80점 이상) 없음.
{%- endif %}
{% if watchlist_rows %}

관찰 목록(65~79점): {{ watchlist_rows | map(attribute="symbol_or_company") | join(", ") }}
{%- endif %}

## 자본 배분 순위

{% if allocation_rows %}
| 순위 | 종목 | 구분 | 기대수익/경로 | 하방 위험 | 확신도 | 권고 행동 |
| ---: | --- | --- | --- | --- | ---: | --- |
{% for row in allocation_rows -%}
| {{ row.rank }} | {{ row.symbol }} | {{ "기존 보유" if row.kind == "existing" else "신규 후보" }} | {{ row.expected_return }} | {{ row.downside_risk }} | {{ row.confidence }} | {{ row.recommended_action }} |
{% endfor %}
{%- else %}
비교 대상 없음.
{%- endif %}

## 신규/갱신 문서

{% if new_documents %}
| 제목 | 출처 | 링크 |
| --- | --- | --- |
{% for doc in new_documents -%}
| {{ doc.title }} | {{ doc.source_name }} | [원문]({{ doc.canonical_url }}) |
{% endfor %}
{%- else %}
신규 문서 없음.
{%- endif %}

## 포트폴리오 현황

{% if position_rows %}
| 종목 | 현재가 | 평가금액 | 비중 |
| --- | ---: | ---: | ---: |
{% for row in position_rows -%}
| {{ row.symbol }} | {{ row.current_price }} | {{ row.market_value }} | {{ row.portfolio_weight }} |
{% endfor %}
{%- else %}
포지션 없음.
{%- endif %}
{% if guardrail_violations %}
## 가드레일 위반

{% for violation in guardrail_violations -%}
- **{{ violation.symbol }}** ({{ violation.rule }}): {{ violation.message }}
{% endfor %}
{%- endif %}
"""
)


class DailyReportContext(BaseModel):
    report_date: date
    narrative: str
    new_documents: list[dict]
    position_rows: list[dict]
    guardrail_violations: list[GuardrailViolation]
    position_signals: list[dict] = []
    tenbagger_candidates: list[dict] = []
    allocation_rows: list[dict] = []


def render_daily_report(context: DailyReportContext) -> str:
    return _TEMPLATE.render(
        report_date=context.report_date,
        narrative=context.narrative,
        new_documents=context.new_documents,
        position_rows=context.position_rows,
        guardrail_violations=context.guardrail_violations,
        position_signals=context.position_signals,
        tenbagger_candidates=context.tenbagger_candidates,
        allocation_rows=context.allocation_rows,
    )

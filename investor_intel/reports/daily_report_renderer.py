from __future__ import annotations

from datetime import date

from jinja2 import Template
from pydantic import BaseModel

from investor_intel.portfolio.guardrails import GuardrailViolation

_TEMPLATE = Template(
    """# 일일 리포트 — {{ report_date.isoformat() }}

## 종합 요약

{{ narrative }}

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


def render_daily_report(context: DailyReportContext) -> str:
    return _TEMPLATE.render(
        report_date=context.report_date,
        narrative=context.narrative,
        new_documents=context.new_documents,
        position_rows=context.position_rows,
        guardrail_violations=context.guardrail_violations,
    )

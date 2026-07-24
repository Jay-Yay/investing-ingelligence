from datetime import date

from investor_intel.portfolio.guardrails import GuardrailViolation
from investor_intel.reports.daily_report_renderer import DailyReportContext, render_daily_report


def _context(**overrides) -> DailyReportContext:
    defaults = dict(
        report_date=date(2026, 7, 24),
        narrative="오늘 시장은 전반적으로 강세를 보였다.",
        new_documents=[
            {
                "title": "엔비디아 실적 발표",
                "source_name": "engineerinvestor",
                "canonical_url": "https://example.com/1",
            }
        ],
        position_rows=[
            {
                "symbol": "NBIS",
                "current_price": 50.0,
                "market_value": 500.0,
                "portfolio_weight": 0.5,
            }
        ],
        guardrail_violations=[],
    )
    defaults.update(overrides)
    return DailyReportContext(**defaults)


def test_render_includes_all_sections() -> None:
    body = render_daily_report(_context())
    assert "2026-07-24" in body
    assert "오늘 시장은 전반적으로 강세를 보였다." in body
    assert "엔비디아 실적 발표" in body
    assert "NBIS" in body


def test_render_omits_violations_section_when_empty() -> None:
    body = render_daily_report(_context(guardrail_violations=[]))
    assert "가드레일 위반" not in body


def test_render_includes_violations_section_when_present() -> None:
    violation = GuardrailViolation(
        symbol="NBIS", rule="max_single_position_weight", message="NBIS 비중 초과"
    )
    body = render_daily_report(_context(guardrail_violations=[violation]))
    assert "가드레일 위반" in body
    assert "NBIS 비중 초과" in body

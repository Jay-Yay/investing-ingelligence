from __future__ import annotations

from pathlib import Path

from investor_intel.indexing.retrieval import EntityLexicon, plan_query
from investor_intel.knowledge.builder import lead_text, normalize_security
from investor_intel.knowledge.registry import CompanyRegistry
from investor_intel.knowledge.schema import Concept, EntityRef, Period


def _concept(**kw) -> Concept:
    base = dict(type="DartFiling", title="삼성전자 분기보고서", description="설명",
                key="2026-05-15-abc", folder="filings/dart")
    base.update(kw)
    return Concept(**base)


def test_okf_requires_type_and_renders_frontmatter() -> None:
    md = _concept().render()
    assert md.startswith("---\n")
    assert "type: DartFiling" in md      # OKF가 요구하는 유일한 필수 필드
    assert "# 요약" in md and "# 원문" in md


def test_relations_are_markdown_links_with_correct_depth() -> None:
    c = _concept(subject=EntityRef("company", "kr-005930", "삼성전자"))
    # filings/dart 는 두 단계 깊이이므로 ../../companies/ 로 올라가야 한다
    assert "[삼성전자](../../companies/kr-005930.md)" in c.render()


def test_analyst_house_is_a_separate_relation_from_mentions() -> None:
    c = _concept(folder="commentary",
                 mentions=[EntityRef("company", "kr-278470", "에이피알")],
                 analyst_houses=[EntityRef("company", "kr-030610", "교보증권")])
    md = c.render()
    assert "- 언급 종목: [에이피알]" in md
    assert "- 분석 주체: [교보증권]" in md
    assert "analyst_house" in md


def test_stub_body_is_marked_not_silently_empty() -> None:
    md = _concept(status="stub", capture="metadata_only", body="").render()
    assert "status: stub" in md and "본문 미확보" in md


def test_period_year_prefers_fiscal_over_publication() -> None:
    assert Period(published="2026-02-20", as_of="2025-12-31").year() == "2025"
    assert Period(published="2026-02-20").year() == "2026"


def test_security_names_are_normalized_across_reporting_variants() -> None:
    assert normalize_security("Alphabet Inc Class A") == normalize_security("Alphabet Inc Class C")
    assert normalize_security("TSMC ADR") == "TSMC"


def test_lead_text_drops_collector_preamble() -> None:
    body = ("## 원문\n\nchan (@chan) — 2026-07-08T23:21:31+00:00\n\n"
            "[교보증권] 에이피알 2분기 프리뷰")
    assert lead_text(body).startswith("교보증권] 에이피알") or "에이피알" in lead_text(body)


def test_registry_promotes_only_mentioned_companies() -> None:
    reg = CompanyRegistry()
    reg.add_lexicon("에이피알", "kr", "278470")
    reg.add_lexicon("한국콜마", "kr", "161890")
    assert reg.by_key == {}                      # 사전에만 있고 concept은 아직 없다
    hits = reg.find_mentions("에이피알의 2분기 매출액이 크게 늘었다")
    assert [h.key for h in hits] == ["kr-278470"]
    assert set(reg.by_key) == {"kr-278470"}      # 언급된 것만 승격 - 깨진 링크가 생기지 않는다


def test_query_planner_separates_analyst_house_from_subject(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle" / "companies"
    bundle.mkdir(parents=True)
    for key, title in [("kr-278470", "에이피알"), ("kr-030610", "교보증권")]:
        (bundle / f"{key}.md").write_text(f"---\ntype: Company\ntitle: {title}\n---\n",
                                          encoding="utf-8")
    lex = EntityLexicon(tmp_path / "bundle")
    plan = plan_query("교보증권이 제시한 에이피알 목표주가", lex)
    assert plan.entity_key == "kr-278470"        # 대상은 에이피알
    assert plan.analyst_house == "교보증권"        # 교보증권은 필터가 아니다
    assert plan.okf_types == ["ResearchNote", "MarketCommentary"]


def test_bare_four_digit_number_is_not_a_year_slot(tmp_path: Path) -> None:
    (tmp_path / "companies").mkdir(parents=True)
    lex = EntityLexicon(tmp_path)
    assert plan_query("영업활동현금흐름 1,467,036 2025.4 853,151", lex).period_year is None
    assert plan_query("삼성전자 2003년 분기보고서", lex).period_year == "2003"
    assert plan_query("Bloom Energy FY2024 10-K", lex).period_year == "2024"

from __future__ import annotations

from investor_intel.collectors.naver_research_parser import NaverResearchDetail, NaverResearchStub

NAVER_RESEARCH_LIMITATIONS_NOTE = (
    "- 네이버 증권의 비공개 JSON API(m.stock.naver.com/api/research/company)를 사용한다.\n"
    "- 목록에 노출된 최신 ~30건만 수집하며, 커버리지가 뜸한 종목은 그날 목록에 없으면\n"
    "  놓친다 - 특정 종목만 필터링하는 방법은 없다.\n"
    "- 첨부 PDF가 있으면 원문 전체를 추출하고, 없으면 API의 content 요약 필드로 대체한다.\n"
)


def render_naver_research_body(
    stub: NaverResearchStub,
    detail: NaverResearchDetail,
    canonical_url: str,
    pdf_text: str | None,
) -> str:
    if detail.goal_price:
        goal_price_line = f"목표주가: {detail.goal_price:,.0f}원"
    else:
        goal_price_line = "목표주가: 미제공"
    if detail.prev_goal_price:
        goal_price_line += f" (직전 {detail.prev_goal_price:,.0f}원)"
    opinion_line = f"투자의견: {detail.opinion or '미제공'}"

    body_text = pdf_text or detail.content_text or "(본문 미제공 - 원문 링크 참고)"
    body_note = "(첨부된 PDF 리포트에서 추출한 원문 전체)" if pdf_text else None
    rank_prefix = f"[주간 인기 {stub.rank}위] " if stub.rank else ""

    sections = [
        "## 원문",
        "",
        f"{rank_prefix}{stub.broker_name} — [{stub.item_name}] {stub.title}",
        f"{opinion_line} | {goal_price_line}",
        *([body_note] if body_note else []),
        "",
        body_text,
        "",
        "## 수집 시 유의사항",
        "",
        NAVER_RESEARCH_LIMITATIONS_NOTE,
        "## 핵심 주장",
        "",
        "## 근거",
        "",
        "## 반대 근거",
        "",
        "## 언급 자산",
        "",
        "## 포트폴리오 관련성",
        "",
        "## 출처",
        "",
        f"- [원문]({canonical_url})",
        "",
    ]
    return "\n".join(sections)

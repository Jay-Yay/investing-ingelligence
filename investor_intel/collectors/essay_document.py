from __future__ import annotations

from investor_intel.collectors.essay_parser import EssayPage
from investor_intel.models.config import InvestorConfig

ESSAY_LIMITATIONS_NOTE = (
    "- 발행일은 페이지에 구조화된 날짜 정보가 없어 최초 수집 시각으로 고정하며, 실제 게시일과 "
    "다를 수 있다.\n"
    "- 이미지, 각주, 인터랙티브 요소는 캡처하지 않는다.\n"
    "- 워드프레스가 아닌 사이트는 일반 폴백 추출(페이지의 모든 <p> 태그)을 사용하며 품질이 "
    "낮을 수 있다.\n"
)


def render_essay_body(
    page: EssayPage,
    investor: InvestorConfig,
    canonical_url: str,
) -> str:
    sections = [
        "## 원문",
        "",
        f"{investor.name} ({investor.fund_name}) — {page.title}",
        "",
        page.body_text,
        "",
        "## 에세이 수집 시 유의사항",
        "",
        ESSAY_LIMITATIONS_NOTE,
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

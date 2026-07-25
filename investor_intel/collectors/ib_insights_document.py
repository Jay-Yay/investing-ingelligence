from __future__ import annotations

from investor_intel.collectors.ib_insights_parser import IBArticle
from investor_intel.models.config import SourceConfig

IB_INSIGHTS_LIMITATIONS_NOTE = (
    "- 각 사가 공개한 인사이트/요약 콘텐츠이며, 기관 고객 전용 셀사이드 리서치 풀 리포트가\n"
    "  아니다.\n"
    "- 인사이트 페이지에 노출된 최신 목록만 수집하며 과거 아카이브는 수집하지 않는다.\n"
    "- 목록이 최신순으로 정렬되어 있다고 가정하고 이전 실행 이후 신규 항목을 판별한다.\n"
    "- 게시일이 목록에 노출되지 않는 사이트는 수집일을 게시일로 대체한다.\n"
)


def render_ib_insights_body(article: IBArticle, source: SourceConfig) -> str:
    sections = [
        "## 원문",
        "",
        f"{source.name} — {article.title}",
        "",
        article.summary or "(요약 미제공 - 원문 링크 참고)",
        "",
        "## 수집 시 유의사항",
        "",
        IB_INSIGHTS_LIMITATIONS_NOTE,
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
        f"- [원문]({article.url})",
        "",
    ]
    return "\n".join(sections)

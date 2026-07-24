from __future__ import annotations

from investor_intel.collectors.naver_parser import NaverPost
from investor_intel.models.config import SourceConfig

NAVER_LIMITATIONS_NOTE = (
    "- 이 컬렉터는 RSS 피드만 사용하며, 모바일 HTML 폴백은 이 단계에서 구현하지 않는다.\n"
    "- 이미지, 첨부파일, 동영상은 캡처하지 않는다.\n"
    "- RSS에 요약만 제공되는 경우 전체 본문이 아닐 수 있다.\n"
)


def render_naver_post_body(
    post: NaverPost,
    source: SourceConfig,
    canonical_url: str,
) -> str:
    sections = [
        "## 원문",
        "",
        f"{source.name} — {post.title} ({post.published_at.isoformat()})",
        "",
        post.description,
        "",
        "## 블로그 수집 시 유의사항",
        "",
        NAVER_LIMITATIONS_NOTE,
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

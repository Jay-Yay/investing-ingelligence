from datetime import UTC, datetime

from investor_intel.collectors.naver_document import (
    NAVER_LIMITATIONS_NOTE,
    render_naver_post_body,
)
from investor_intel.collectors.naver_parser import NaverPost
from investor_intel.models.config import SourceConfig


def _source() -> SourceConfig:
    return SourceConfig(
        id="naver_engineerinvestor",
        type="naver",
        name="engineerinvestor",
        url="https://m.blog.naver.com/engineerinvestor",
        author="engineerinvestor",
    )


def _post() -> NaverPost:
    return NaverPost(
        guid="https://blog.naver.com/engineerinvestor/223456789",
        title="엔비디아 실적 발표 후기",
        link="https://blog.naver.com/engineerinvestor/223456789",
        description="<p>엔비디아 이번 분기 실적이 시장 예상을 상회했다.</p>",
        published_at=datetime(2024, 5, 1, 21, 0, tzinfo=UTC),
    )


def test_render_includes_all_required_sections() -> None:
    body = render_naver_post_body(
        _post(), _source(), "https://blog.naver.com/engineerinvestor/223456789"
    )
    for section in (
        "## 원문",
        "## 블로그 수집 시 유의사항",
        "## 핵심 주장",
        "## 근거",
        "## 반대 근거",
        "## 언급 자산",
        "## 포트폴리오 관련성",
        "## 출처",
    ):
        assert section in body

    assert "엔비디아 실적 발표 후기" in body
    assert "엔비디아 이번 분기 실적" in body
    assert "https://blog.naver.com/engineerinvestor/223456789" in body


def test_render_includes_limitations_note_verbatim() -> None:
    body = render_naver_post_body(_post(), _source(), "https://example.com")
    assert NAVER_LIMITATIONS_NOTE in body

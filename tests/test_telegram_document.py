from datetime import UTC, datetime

from investor_intel.collectors.telegram_document import (
    TELEGRAM_LIMITATIONS_NOTE,
    render_telegram_message_body,
)
from investor_intel.collectors.telegram_link_article import ArticleAttachment
from investor_intel.collectors.telegram_parser import TelegramMessage
from investor_intel.models.config import SourceConfig


def _source() -> SourceConfig:
    return SourceConfig(
        id="telegram_allbareun",
        type="telegram",
        name="allbareun",
        url="https://t.me/s/allbareun",
        author=None,
    )


def _message() -> TelegramMessage:
    return TelegramMessage(
        message_id="101",
        channel="allbareun",
        text="엔비디아 실적 발표\n시장 예상 상회",
        link="https://t.me/allbareun/101",
        published_at=datetime(2024, 5, 1, 12, 0, tzinfo=UTC),
    )


def test_render_includes_all_required_sections() -> None:
    body = render_telegram_message_body(
        _message(), _source(), "https://t.me/allbareun/101"
    )
    for section in (
        "## 원문",
        "## 텔레그램 수집 시 유의사항",
        "## 핵심 주장",
        "## 근거",
        "## 반대 근거",
        "## 언급 자산",
        "## 포트폴리오 관련성",
        "## 출처",
    ):
        assert section in body

    assert "엔비디아 실적 발표" in body
    assert "https://t.me/allbareun/101" in body
    assert "allbareun" in body


def test_render_includes_limitations_note_verbatim() -> None:
    body = render_telegram_message_body(_message(), _source(), "https://example.com")
    assert TELEGRAM_LIMITATIONS_NOTE in body


def test_render_without_articles_omits_attached_article_section() -> None:
    body = render_telegram_message_body(_message(), _source(), "https://t.me/allbareun/101")
    assert "## 첨부 기사 원문" not in body


def test_render_includes_successful_article_body_and_source_link() -> None:
    articles = [
        ArticleAttachment(
            url="https://www.hankyung.com/article/1",
            title="테스트 기사 제목",
            body_text="기사 본문 내용입니다.",
        )
    ]
    body = render_telegram_message_body(
        _message(), _source(), "https://t.me/allbareun/101", articles
    )

    assert "## 첨부 기사 원문" in body
    assert "### 테스트 기사 제목" in body
    assert "기사 본문 내용입니다." in body
    assert "- [기사 원문](https://www.hankyung.com/article/1)" in body


def test_render_shows_error_for_failed_article_and_excludes_it_from_source_list() -> None:
    articles = [
        ArticleAttachment(url="https://example.com/blocked", error="403 Forbidden"),
    ]
    body = render_telegram_message_body(
        _message(), _source(), "https://t.me/allbareun/101", articles
    )

    assert "### https://example.com/blocked" in body
    assert "[기사 본문 추출 실패: 403 Forbidden]" in body
    assert "- [기사 원문](https://example.com/blocked)" not in body

from datetime import UTC, datetime

from investor_intel.collectors.telegram_document import (
    TELEGRAM_LIMITATIONS_NOTE,
    render_telegram_message_body,
)
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

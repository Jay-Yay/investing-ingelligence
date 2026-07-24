from datetime import UTC, datetime

from investor_intel.collectors.telegram_private_document import (
    TELEGRAM_PRIVATE_LIMITATIONS_NOTE,
    render_telethon_message_body,
)
from investor_intel.collectors.telethon_client import TelethonMessage
from investor_intel.models.config import SourceConfig


def _source() -> SourceConfig:
    return SourceConfig(
        id="telegram_private_allbareun",
        type="telegram_private",
        name="allbareun (비공개)",
        url="https://t.me/allbareun_private",
        author=None,
    )


def _message() -> TelethonMessage:
    return TelethonMessage(
        id=555, text="비공개 채널 메시지 본문", date=datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
    )


def test_render_includes_all_required_sections() -> None:
    body = render_telethon_message_body(_message(), _source(), "https://t.me/allbareun/555")
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

    assert "비공개 채널 메시지 본문" in body
    assert "https://t.me/allbareun/555" in body


def test_render_includes_limitations_note_verbatim() -> None:
    body = render_telethon_message_body(_message(), _source(), "https://example.com")
    assert TELEGRAM_PRIVATE_LIMITATIONS_NOTE in body
    assert "인증된 사용자 세션" in body

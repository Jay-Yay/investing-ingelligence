from pathlib import Path

from investor_intel.collectors.telegram_parser import (
    parse_all_message_ids,
    parse_telegram_channel_html,
)

FIXTURES = Path(__file__).parent / "fixtures" / "telegram"


def _html() -> str:
    return (FIXTURES / "channel_preview.html").read_text(encoding="utf-8")


def test_parses_text_messages_skipping_empty_media_only() -> None:
    messages = parse_telegram_channel_html(_html(), channel="allbareun")
    # 3 messages in fixture, but the photo-only one (id 102) has no text and is skipped
    assert len(messages) == 2
    assert [m.message_id for m in messages] == ["101", "103"]


def test_extracts_nested_tags_and_br_as_newline() -> None:
    messages = parse_telegram_channel_html(_html(), channel="allbareun")
    first = messages[0]
    assert first.text == "엔비디아 실적 발표\n시장 예상 상회"


def test_extracts_link_and_timestamp() -> None:
    messages = parse_telegram_channel_html(_html(), channel="allbareun")
    first = messages[0]
    assert first.link == "https://t.me/allbareun/101"
    assert first.published_at.isoformat() == "2024-05-01T12:00:00+00:00"
    assert first.channel == "allbareun"


def test_parse_all_message_ids_includes_text_less_photo_message() -> None:
    # the fixture's message 102 is photo-only (no text) and is excluded by
    # parse_telegram_channel_html, but its ID must still be visible for pagination cursors
    ids = parse_all_message_ids(_html())
    assert ids == ["101", "102", "103"]


def test_second_text_message_parses_independently() -> None:
    messages = parse_telegram_channel_html(_html(), channel="allbareun")
    second = messages[1]
    assert second.message_id == "103"
    assert second.text == "테슬라 밸류에이션 점검 링크 공유"
    assert second.link == "https://t.me/allbareun/103"

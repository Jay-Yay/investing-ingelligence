from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser


@dataclass
class TelegramMessage:
    message_id: str
    channel: str
    text: str
    link: str
    published_at: datetime


@dataclass
class _PendingMessage:
    data_post: str
    text_parts: list[str] = field(default_factory=list)
    link: str | None = None
    datetime_raw: str | None = None


class _ChannelPreviewParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pending: list[_PendingMessage] = []
        self._div_depth = 0
        self._message_div_depth: int | None = None
        self._text_div_depth: int | None = None
        self._current: _PendingMessage | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = (attrs_dict.get("class") or "").split()

        if tag == "div":
            self._div_depth += 1
            if "tgme_widget_message" in classes and "data-post" in attrs_dict:
                self._current = _PendingMessage(data_post=attrs_dict["data-post"] or "")
                self._message_div_depth = self._div_depth
            if self._current is not None and "tgme_widget_message_text" in classes:
                self._text_div_depth = self._div_depth
        elif tag == "br" and self._text_div_depth is not None:
            if self._current is not None:
                self._current.text_parts.append("\n")
        elif tag == "a" and self._current is not None and "tgme_widget_message_date" in classes:
            self._current.link = attrs_dict.get("href")
        elif tag == "time" and self._current is not None:
            self._current.datetime_raw = attrs_dict.get("datetime")

    def handle_endtag(self, tag: str) -> None:
        if tag != "div":
            return
        if self._text_div_depth is not None and self._div_depth == self._text_div_depth:
            self._text_div_depth = None
        if self._message_div_depth is not None and self._div_depth == self._message_div_depth:
            assert self._current is not None
            self.pending.append(self._current)
            self._current = None
            self._message_div_depth = None
        self._div_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._text_div_depth is not None and self._current is not None:
            self._current.text_parts.append(data)


def parse_telegram_channel_html(html_text: str, channel: str) -> list[TelegramMessage]:
    parser = _ChannelPreviewParser()
    parser.feed(html_text)

    messages: list[TelegramMessage] = []
    for pending in parser.pending:
        text = "".join(pending.text_parts).strip()
        if not text:
            continue
        message_id = pending.data_post.rsplit("/", 1)[-1]
        link = pending.link or f"https://t.me/{channel}/{message_id}"
        published_at = datetime.fromisoformat(pending.datetime_raw or "")
        messages.append(
            TelegramMessage(
                message_id=message_id,
                channel=channel,
                text=text,
                link=link,
                published_at=published_at,
            )
        )
    return messages

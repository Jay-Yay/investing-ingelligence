from __future__ import annotations

from datetime import date, timedelta

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.telegram_document import render_telegram_message_body
from investor_intel.collectors.telegram_parser import (
    TelegramMessage,
    parse_all_message_ids,
    parse_telegram_channel_html,
)
from investor_intel.models.config import SourceConfig

_MAX_PAGES = 10


def _extract_channel(source_url: str) -> str:
    return source_url.rstrip("/").rsplit("/", 1)[-1]


class TelegramCollector:
    def __init__(
        self,
        source: SourceConfig,
        client: SimpleHttpClient,
        checkpoint_store: CheckpointStore,
    ) -> None:
        self.source_id = source.id
        self._source = source
        self._client = client
        self._checkpoint_store = checkpoint_store

    def _fetch_all_messages(self) -> list[TelegramMessage]:
        channel = _extract_channel(self._source.url)
        all_messages: list[TelegramMessage] = []
        seen_ids: set[str] = set()
        next_url = self._source.url
        previous_min_id: int | None = None

        for _ in range(_MAX_PAGES):
            html_text = self._client.get_text(next_url)
            all_ids_on_page = parse_all_message_ids(html_text)
            if not all_ids_on_page:
                break

            # the pagination cursor must use the lowest ID on the page regardless of
            # text-filtering - a text-less (photo/video-only) message can be the lowest ID,
            # and skipping past it here would silently truncate history before it
            min_id = min(int(message_id) for message_id in all_ids_on_page)
            if previous_min_id is not None and min_id >= previous_min_id:
                break  # cursor didn't advance - stop rather than loop forever
            previous_min_id = min_id

            page_messages = parse_telegram_channel_html(html_text, channel=channel)
            new_messages = [m for m in page_messages if m.message_id not in seen_ids]
            all_messages.extend(new_messages)
            seen_ids.update(m.message_id for m in new_messages)

            next_url = f"{self._source.url}?before={min_id}"

        return all_messages

    def _build_item(self, message: TelegramMessage) -> CollectItem:
        body = render_telegram_message_body(message, self._source, message.link)

        return CollectItem(
            source_specific_id=message.message_id,
            canonical_url=message.link,
            title=None,
            author=self._source.name,
            published_at=message.published_at,
            updated_at=None,
            language="ko",
            body_text=body,
            content_capture_mode="full",
            companies=[],
            document_type="telegram_message",
            filing_type=None,
            reporting_period=None,
            accession_number=None,
        )

    def _collect(self, messages_to_process: list[TelegramMessage]) -> CollectResult:
        items: list[CollectItem] = []
        errors: list[str] = []
        for message in messages_to_process:
            try:
                items.append(self._build_item(message))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{message.message_id}: {exc}")

        if items:
            self._checkpoint_store.record_success(
                self.source_id, last_seen_id=items[-1].source_specific_id
            )
        elif errors:
            self._checkpoint_store.record_failure(self.source_id)

        return CollectResult(
            source_id=self.source_id,
            success=not errors,
            items=items,
            errors=errors,
            new_count=len(items),
        )

    def backfill(self, days: int) -> CollectResult:
        all_messages = self._fetch_all_messages()
        cutoff = date.today() - timedelta(days=days)
        to_process = sorted(
            (m for m in all_messages if m.published_at.date() >= cutoff),
            key=lambda m: m.published_at,
        )
        result = self._collect(to_process)
        state = self._checkpoint_store.get_state(self.source_id)
        state.backfill_completed = True
        self._checkpoint_store.save_state(state)
        return result

    def collect_incremental(self) -> CollectResult:
        all_messages = self._fetch_all_messages()
        state = self._checkpoint_store.get_state(self.source_id)

        if state.last_seen_id is None:
            to_process = list(all_messages)
        else:
            last_seen_published_at = next(
                (
                    m.published_at
                    for m in all_messages
                    if m.message_id == state.last_seen_id
                ),
                None,
            )
            to_process = (
                list(all_messages)
                if last_seen_published_at is None
                else [m for m in all_messages if m.published_at > last_seen_published_at]
            )

        to_process.sort(key=lambda m: m.published_at)
        return self._collect(to_process)

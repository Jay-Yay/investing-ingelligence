from __future__ import annotations

from datetime import date, timedelta

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.telegram_document import render_telegram_message_body
from investor_intel.collectors.telegram_parser import TelegramMessage, parse_telegram_channel_html
from investor_intel.models.config import SourceConfig


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
        html_text = self._client.get_text(self._source.url)
        return parse_telegram_channel_html(html_text, channel=channel)

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

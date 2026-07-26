from __future__ import annotations

import asyncio
from datetime import date, timedelta

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.telegram_private_document import render_telethon_message_body
from investor_intel.collectors.telethon_client import TelethonClientProtocol, TelethonMessage
from investor_intel.models.config import SourceConfig

_FETCH_LIMIT = 200


def _extract_channel(source_url: str) -> str:
    return source_url.rstrip("/").rsplit("/", 1)[-1]


class TelethonPrivateChannelCollector:
    def __init__(
        self,
        source: SourceConfig,
        client: TelethonClientProtocol,
        checkpoint_store: CheckpointStore,
    ) -> None:
        self.source_id = source.id
        self._source = source
        self._client = client
        self._checkpoint_store = checkpoint_store
        self._entity = _extract_channel(source.url)

    async def _fetch_all_messages_async(self) -> list[TelethonMessage]:
        return [
            message
            async for message in self._client.iter_messages(self._entity, limit=_FETCH_LIMIT)
        ]

    def _fetch_all_messages(self) -> list[TelethonMessage]:
        return asyncio.run(self._fetch_all_messages_async())

    def _build_item(self, message: TelethonMessage) -> CollectItem:
        canonical_url = f"https://t.me/{self._entity}/{message.id}"
        body = render_telethon_message_body(message, self._source, canonical_url)

        return CollectItem(
            source_specific_id=str(message.id),
            canonical_url=canonical_url,
            title=None,
            author=self._source.author or self._source.name,
            published_at=message.date,
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

    def _collect(self, messages_to_process: list[TelethonMessage]) -> CollectResult:
        items: list[CollectItem] = []
        errors: list[str] = []
        for message in messages_to_process:
            try:
                items.append(self._build_item(message))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{message.id}: {exc}")

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

    def _fetch_or_fail(self) -> tuple[list[TelethonMessage] | None, CollectResult | None]:
        try:
            return self._fetch_all_messages(), None
        except Exception as exc:  # noqa: BLE001
            self._checkpoint_store.record_failure(self.source_id)
            failure = CollectResult(
                source_id=self.source_id, success=False, items=[], errors=[str(exc)]
            )
            return None, failure

    def backfill(self, days: int) -> CollectResult:
        all_messages, failure = self._fetch_or_fail()
        if failure is not None:
            return failure
        assert all_messages is not None

        cutoff = date.today() - timedelta(days=days)
        to_process = sorted(
            (m for m in all_messages if m.date.date() >= cutoff), key=lambda m: m.date
        )
        result = self._collect(to_process)
        state = self._checkpoint_store.get_state(self.source_id)
        state.backfill_completed = True
        self._checkpoint_store.save_state(state)
        return result

    def collect_incremental(self) -> CollectResult:
        all_messages, failure = self._fetch_or_fail()
        if failure is not None:
            return failure
        assert all_messages is not None

        state = self._checkpoint_store.get_state(self.source_id)
        if state.last_seen_id is None:
            to_process = list(all_messages)
        else:
            last_seen_date = next(
                (m.date for m in all_messages if str(m.id) == state.last_seen_id), None
            )
            to_process = (
                list(all_messages)
                if last_seen_date is None
                else [m for m in all_messages if m.date > last_seen_date]
            )

        to_process.sort(key=lambda m: m.date)
        return self._collect(to_process)

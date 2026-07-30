from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.essay_document import render_essay_body
from investor_intel.collectors.essay_parser import parse_essay_html
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.models.config import InvestorConfig
from investor_intel.storage.sqlite_index import get_document_by_canonical_url


class EssayCollector:
    def __init__(
        self,
        investor: InvestorConfig,
        client: SimpleHttpClient,
        checkpoint_store: CheckpointStore,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        if not investor.related_essay_url:
            raise ValueError(f"investor {investor.id} has no related_essay_url")
        self.source_id = f"essay_{investor.id}"
        self._investor = investor
        self._url = investor.related_essay_url
        self._client = client
        self._checkpoint_store = checkpoint_store
        self._conn = conn

    def _pinned_published_at(self) -> datetime:
        # A single fixed essay page has no real "publish date" of its own, so the first ever
        # collection pins one (checkpoint_store, below) and every later run reuses it - but that
        # pin lives in the local sqlite checkpoint, which is per-machine and not synced across
        # environments (see vault/00_System/Runbook.md). Two machines each doing a first-ever
        # collect would otherwise each pin their own "now", producing the same document under two
        # different date-prefixed filenames. Checking the (vault-derived) documents index first -
        # which IS shared once pulled - lets a second machine reuse whatever date the first one
        # already picked, as long as that vault content has been pulled locally.
        if self._conn is not None:
            existing = get_document_by_canonical_url(self._conn, self._url)
            if existing is not None:
                return datetime.fromisoformat(existing["published_at"])
        state = self._checkpoint_store.get_state(self.source_id)
        if state.last_seen_id is not None:
            return datetime.fromisoformat(state.last_seen_id)
        return datetime.now(UTC)

    def _collect(self) -> CollectResult:
        try:
            html_text = self._client.get_text(self._url)
            page = parse_essay_html(html_text)
            published_at = self._pinned_published_at()
            body = render_essay_body(page, self._investor, self._url)
        except Exception as exc:  # noqa: BLE001
            self._checkpoint_store.record_failure(self.source_id)
            return CollectResult(
                source_id=self.source_id, success=False, items=[], errors=[str(exc)]
            )

        item = CollectItem(
            source_specific_id=None,
            canonical_url=self._url,
            title=page.title,
            author=self._investor.name,
            published_at=published_at,
            updated_at=None,
            language="en",
            body_text=body,
            content_capture_mode="full",
            companies=[],
            document_type="essay",
            filing_type=None,
            reporting_period=None,
            accession_number=None,
        )
        self._checkpoint_store.record_success(
            self.source_id, last_seen_id=published_at.isoformat()
        )
        return CollectResult(
            source_id=self.source_id, success=True, items=[item], errors=[], new_count=1
        )

    def backfill(self, days: int) -> CollectResult:
        # A single fixed page has no "window" to backfill within - every call fetches the
        # same URL. `days` is accepted only for Collector protocol conformance.
        result = self._collect()
        state = self._checkpoint_store.get_state(self.source_id)
        state.backfill_completed = True
        self._checkpoint_store.save_state(state)
        return result

    def collect_incremental(self) -> CollectResult:
        return self._collect()

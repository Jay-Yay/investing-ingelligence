from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from investor_intel.storage.sqlite_index import get_collector_state, save_collector_state


class RateLimiter:
    def __init__(self, max_per_second: float) -> None:
        if max_per_second <= 0:
            raise ValueError("max_per_second must be positive")
        self._min_interval = 1.0 / max_per_second
        self._last_call: float | None = None

    def acquire(self) -> None:
        now = time.monotonic()
        if self._last_call is not None:
            elapsed = now - self._last_call
            wait = self._min_interval - elapsed
            if wait > 0:
                time.sleep(wait)
        self._last_call = time.monotonic()


@dataclass
class CollectItem:
    source_specific_id: str | None
    canonical_url: str
    title: str | None
    author: str | None
    published_at: datetime
    updated_at: datetime | None
    language: str
    body_text: str
    content_capture_mode: str
    content_capture_reason: str | None = None
    assets: list[dict] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    document_type: str = "opinion"
    filing_type: str | None = None
    reporting_period: str | None = None
    accession_number: str | None = None


@dataclass
class CollectResult:
    source_id: str
    success: bool
    items: list[CollectItem]
    errors: list[str]
    new_count: int = 0
    skipped_count: int = 0


@dataclass
class CollectorState:
    source_id: str
    last_success_at: datetime | None
    last_seen_id: str | None
    last_accession_number: str | None
    failure_count: int
    next_retry_at: datetime | None
    backfill_completed: bool


class Collector(Protocol):
    source_id: str

    def backfill(self, days: int) -> CollectResult: ...

    def collect_incremental(self) -> CollectResult: ...


class CheckpointStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_state(self, source_id: str) -> CollectorState:
        row = get_collector_state(self._conn, source_id)
        if row is None:
            return CollectorState(
                source_id=source_id,
                last_success_at=None,
                last_seen_id=None,
                last_accession_number=None,
                failure_count=0,
                next_retry_at=None,
                backfill_completed=False,
            )
        return CollectorState(
            source_id=row["source_id"],
            last_success_at=(
                datetime.fromisoformat(row["last_success_at"])
                if row["last_success_at"]
                else None
            ),
            last_seen_id=row["last_seen_id"],
            last_accession_number=row["last_accession_number"],
            failure_count=row["failure_count"],
            next_retry_at=(
                datetime.fromisoformat(row["next_retry_at"]) if row["next_retry_at"] else None
            ),
            backfill_completed=bool(row["backfill_completed"]),
        )

    def save_state(self, state: CollectorState) -> None:
        save_collector_state(
            self._conn,
            source_id=state.source_id,
            last_success_at=(
                state.last_success_at.isoformat() if state.last_success_at else None
            ),
            last_seen_id=state.last_seen_id,
            last_accession_number=state.last_accession_number,
            failure_count=state.failure_count,
            next_retry_at=state.next_retry_at.isoformat() if state.next_retry_at else None,
            backfill_completed=state.backfill_completed,
        )

    def record_failure(self, source_id: str, base_backoff_seconds: int = 60) -> CollectorState:
        state = self.get_state(source_id)
        state.failure_count += 1
        backoff = base_backoff_seconds * (2 ** (state.failure_count - 1))
        state.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
        self.save_state(state)
        return state

    def record_success(self, source_id: str, last_seen_id: str | None = None) -> CollectorState:
        state = self.get_state(source_id)
        state.failure_count = 0
        state.next_retry_at = None
        state.last_success_at = datetime.now(timezone.utc)
        if last_seen_id is not None:
            state.last_seen_id = last_seen_id
        self.save_state(state)
        return state

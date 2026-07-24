from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from investor_intel.collectors.base import CollectItem, Collector, CollectResult
from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import AssetMention, ContentCapture, SourceDocument
from investor_intel.storage.content_hash import compute_content_hash, compute_stable_id
from investor_intel.storage.obsidian_repo import write_document
from investor_intel.storage.sqlite_index import find_duplicate, upsert_document


@dataclass
class PersistResult:
    count: int
    errors: list[str] = field(default_factory=list)


@dataclass
class SourceRunResult:
    source_id: str
    persisted: int
    errors: list[str] = field(default_factory=list)


def collect_item_to_source_document(
    item: CollectItem, source_type: SourceType, source_name: str
) -> tuple[SourceDocument, str]:
    content_hash = compute_content_hash(item.body_text)
    stable_id = compute_stable_id(
        source_type.value, source_name, item.source_specific_id, item.canonical_url
    )
    doc = SourceDocument(
        id=stable_id,
        source_type=source_type,
        source_name=source_name,
        author=item.author,
        title=item.title,
        source_url=item.canonical_url,
        source_specific_id=item.source_specific_id,
        published_at=item.published_at,
        collected_at=datetime.now(UTC),
        updated_at=item.updated_at,
        language=item.language,
        content_hash=content_hash,
        content_capture=ContentCapture(
            mode=ContentCaptureMode(item.content_capture_mode),
            reason=item.content_capture_reason,
        ),
        assets=[AssetMention(**asset) for asset in item.assets],
        companies=item.companies,
        themes=item.themes,
        document_type=item.document_type,
        filing_type=item.filing_type,
        reporting_period=item.reporting_period,
        accession_number=item.accession_number,
    )
    return doc, item.body_text


def persist_collect_result(
    result: CollectResult,
    source_type: SourceType,
    source_name: str,
    vault_path: Path,
    conn: sqlite3.Connection,
) -> PersistResult:
    count = 0
    errors: list[str] = []

    for item in result.items:
        try:
            doc, body = collect_item_to_source_document(item, source_type, source_name)

            existing_id = find_duplicate(
                conn,
                source_type=source_type.value,
                source_name=source_name,
                source_specific_id=item.source_specific_id,
                canonical_url=item.canonical_url,
                content_hash=doc.content_hash,
                title=item.title,
                author=item.author,
                published_at=item.published_at.isoformat(),
            )
            if existing_id is not None:
                doc = doc.model_copy(update={"id": existing_id})

            file_path = write_document(vault_path, doc, body)
            upsert_document(
                conn, doc, file_path=str(file_path), source_specific_id=item.source_specific_id
            )
            count += 1
        except Exception as exc:  # noqa: BLE001
            identifier = item.source_specific_id or item.canonical_url
            errors.append(f"{identifier}: {exc}")

    return PersistResult(count=count, errors=errors)


def run_collectors(
    entries: list[tuple[Collector, SourceType, str]],
    vault_path: Path,
    conn: sqlite3.Connection,
    backfill_days: int | None = None,
) -> list[SourceRunResult]:
    results: list[SourceRunResult] = []

    for collector, source_type, source_name in entries:
        errors: list[str] = []
        persisted = 0
        try:
            collect_result = (
                collector.backfill(backfill_days)
                if backfill_days is not None
                else collector.collect_incremental()
            )
            errors.extend(collect_result.errors)
            persist_result = persist_collect_result(
                collect_result, source_type, source_name, vault_path, conn
            )
            persisted = persist_result.count
            errors.extend(persist_result.errors)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

        results.append(
            SourceRunResult(source_id=collector.source_id, persisted=persisted, errors=errors)
        )

    return results

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from investor_intel.llm.client import AnthropicClient
from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.llm.extraction import extract_claims
from investor_intel.models.analysis import ExtractionResult
from investor_intel.pipeline.claims_splice import splice_claims_into_body
from investor_intel.storage.content_hash import compute_content_hash
from investor_intel.storage.obsidian_repo import path_for_document, read_document, render_document
from investor_intel.storage.sqlite_index import upsert_document

_CHARS_PER_TOKEN_ESTIMATE = 4


@dataclass
class AnalyzeResult:
    processed: int
    errors: list[str] = field(default_factory=list)
    extractions: dict[str, ExtractionResult] = field(default_factory=dict)


def find_unprocessed_document_paths(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT file_path FROM documents WHERE llm_processed = 0").fetchall()
    return [row["file_path"] for row in rows]


def analyze_pending_documents(
    conn: sqlite3.Connection,
    vault_path: Path,
    client: AnthropicClient,
    cost_tracker: CostTracker,
    system_prompt: str,
) -> AnalyzeResult:
    processed = 0
    errors: list[str] = []
    extractions: dict[str, ExtractionResult] = {}

    for file_path in find_unprocessed_document_paths(conn):
        if not cost_tracker.is_within_budget():
            break

        try:
            doc, body = read_document(Path(file_path))
            extraction = extract_claims(client, document_body=body, system_prompt=system_prompt)

            input_tokens = (len(body) + len(system_prompt)) // _CHARS_PER_TOKEN_ESTIMATE
            output_tokens = len(json.dumps(extraction.model_dump())) // _CHARS_PER_TOKEN_ESTIMATE
            cost_tracker.record_usage(client.model, input_tokens, output_tokens)

            spliced_body = splice_claims_into_body(body, extraction)
            updated_doc = doc.model_copy(
                update={
                    "llm_processed": True,
                    "llm_model": client.model,
                    "content_hash": compute_content_hash(spliced_body),
                }
            )
            path = path_for_document(vault_path, updated_doc)
            path.write_text(render_document(updated_doc, spliced_body), encoding="utf-8")
            upsert_document(
                conn,
                updated_doc,
                file_path=str(path),
                source_specific_id=updated_doc.source_specific_id,
            )

            extractions[updated_doc.id] = extraction
            processed += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{file_path}: {exc}")

    return AnalyzeResult(processed=processed, errors=errors, extractions=extractions)

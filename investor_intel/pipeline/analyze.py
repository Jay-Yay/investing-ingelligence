from __future__ import annotations

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


@dataclass
class ClaimDigestEntry:
    """One extracted claim plus the source metadata needed to rank it (recency, origin)."""

    published_at: str
    source_type: str
    source_name: str
    source_url: str
    assets: list[str]
    direction: str
    confidence: str
    claim: str


@dataclass
class AnalyzeResult:
    processed: int
    errors: list[str] = field(default_factory=list)
    extractions: dict[str, ExtractionResult] = field(default_factory=dict)
    digest: list[ClaimDigestEntry] = field(default_factory=list)


def find_unprocessed_document_paths(conn: sqlite3.Connection) -> list[str]:
    """미분석 문서 경로를 최신 발행일 순으로 반환한다.

    일일 LLM 예산이 소진되어 이번 실행에서 일부만 처리하게 되더라도, 오래된 백로그가
    최근 문서를 밀어내지 않고 최신성이 높은 문서부터 우선 분석되도록 정렬한다.
    """
    rows = conn.execute(
        "SELECT file_path FROM documents WHERE llm_processed = 0 ORDER BY published_at DESC"
    ).fetchall()
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
    digest: list[ClaimDigestEntry] = []

    for file_path in find_unprocessed_document_paths(conn):
        if not cost_tracker.is_within_budget():
            break

        try:
            doc, body = read_document(Path(file_path))
            outcome = extract_claims(client, document_body=body, system_prompt=system_prompt)
            extraction = outcome.result

            cost_tracker.record_usage(
                client.model, outcome.usage.input_tokens, outcome.usage.output_tokens
            )

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
            for claim in extraction.claims:
                digest.append(
                    ClaimDigestEntry(
                        published_at=updated_doc.published_at.isoformat(),
                        source_type=updated_doc.source_type.value,
                        source_name=updated_doc.source_name,
                        source_url=updated_doc.source_url,
                        assets=claim.assets,
                        direction=claim.direction.value,
                        confidence=claim.confidence.value,
                        claim=claim.claim,
                    )
                )
            processed += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{file_path}: {exc}")

    digest.sort(key=lambda entry: entry.published_at, reverse=True)
    return AnalyzeResult(processed=processed, errors=errors, extractions=extractions, digest=digest)

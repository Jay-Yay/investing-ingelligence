from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from investor_intel.llm.client import AnthropicClient
from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.llm.extraction import extract_claims
from investor_intel.models.analysis import ExtractionResult
from investor_intel.models.common import SourceType
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


# DART/SEC 공시와 보유 종목 웹 검색 스크랩은 source_name에 티커(KR 종목코드 또는 US 심볼)를
# 그대로 담는다 (collect.py, web_research.py 참고) - 다른 소스(Naver/Telegram/13F/Essay/IB)는
# 블로거·투자자·은행 단위라 source_name만으로 종목을 특정할 수 없어 종목 팔로업 창 대상에서
# 제외한다.
_TICKER_TAGGED_SOURCE_TYPES = (
    SourceType.DART.value,
    SourceType.SEC_FILING.value,
    SourceType.WEB_SEARCH.value,
)

DEFAULT_RECENT_DAYS = 7
DEFAULT_TICKER_FOLLOWUP_DAYS = 180


def find_unprocessed_document_paths(
    conn: sqlite3.Connection,
    portfolio_tickers: set[str] | None = None,
    now: datetime | None = None,
    recent_days: int = DEFAULT_RECENT_DAYS,
    ticker_followup_days: int = DEFAULT_TICKER_FOLLOWUP_DAYS,
) -> list[str]:
    """미분석 문서 경로를 최신 발행일 순으로 반환한다.

    수십 년치 히스토리컬 백필(예: 1999년 DART 공시)까지 매번 분석 대상에 올리면 하루 LLM
    예산이 오래된 문서 처리에 소진돼버리므로, 아래 두 창(window)의 합집합으로만 제한한다:
    1) 발행일이 최근 `recent_days`일 이내인 모든 문서 (일반 시황 팔로업)
    2) 포트폴리오 보유 종목에 한해 `ticker_followup_days`일 이내인 문서 (보유 종목은
       실적·공시 흐름을 더 길게 추적해야 하므로 더 긴 팔로업 창을 준다)

    일일 예산이 소진되어 이번 실행에서 일부만 처리하게 되더라도, 이 창 안에서 오래된
    문서가 최신 문서를 밀어내지 않도록 발행일 최신순으로 정렬한다.
    """
    now = now or datetime.now(UTC)
    recent_cutoff = (now - timedelta(days=recent_days)).isoformat()

    query = "SELECT file_path FROM documents WHERE llm_processed = 0 AND (published_at >= ?"
    params: list[str] = [recent_cutoff]

    if portfolio_tickers:
        ticker_cutoff = (now - timedelta(days=ticker_followup_days)).isoformat()
        source_type_placeholders = ", ".join("?" for _ in _TICKER_TAGGED_SOURCE_TYPES)
        ticker_placeholders = ", ".join("?" for _ in portfolio_tickers)
        query += (
            f" OR (source_type IN ({source_type_placeholders}) "
            f"AND source_name IN ({ticker_placeholders}) AND published_at >= ?)"
        )
        params.extend(_TICKER_TAGGED_SOURCE_TYPES)
        params.extend(portfolio_tickers)
        params.append(ticker_cutoff)

    query += ") ORDER BY published_at DESC"

    rows = conn.execute(query, params).fetchall()
    return [row["file_path"] for row in rows]


def analyze_pending_documents(
    conn: sqlite3.Connection,
    vault_path: Path,
    client: AnthropicClient,
    cost_tracker: CostTracker,
    system_prompt: str,
    portfolio_tickers: set[str] | None = None,
) -> AnalyzeResult:
    processed = 0
    errors: list[str] = []
    extractions: dict[str, ExtractionResult] = {}
    digest: list[ClaimDigestEntry] = []

    for file_path in find_unprocessed_document_paths(conn, portfolio_tickers=portfolio_tickers):
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

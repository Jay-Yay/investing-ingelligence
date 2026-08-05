from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from investor_intel.llm.client import AnthropicClient
from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.llm.extraction import extract_claims, extract_claims_batch
from investor_intel.models.analysis import ExtractionResult
from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import SourceDocument
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

# 여러 문서를 한 번의 LLM 호출로 묶을 때(짧은 텔레그램/네이버 게시물 등) 배치 하나의 최대
# 문서 수 / 누적 글자 수. 둘 중 하나라도 넘으면 그 시점까지 모은 배치를 바로 호출한다 -
# 배치가 너무 커지면 한 번의 실패(스키마 불일치 등)로 잃는 범위가 커지고, 개별 폴백 비용도
# 커지기 때문에 상한을 둔다.
DEFAULT_BATCH_SIZE = 8
DEFAULT_BATCH_CHAR_LIMIT = 12_000

RULE_BASED_SKIP_MODEL_TAG = "rule_based_skip"

# "요즘 많이 보는 리포트 TOP 10" 류 - 실제 기사 본문 없이 인기 리포트 링크만 나열하는
# 텔레그램 다이제스트 패턴. 2026-08 수동 backlog 분석(382건)에서 이 패턴에 매칭된 문서는
# 예외 없이 핵심 주장 0건이었다.
_ZERO_CONTENT_MARKERS = ("요즘 많이 보는 리포트",)

_RAW_SECTION_RE = re.compile(r"## 원문\n(.*?)(?=\n## |\Z)", re.DOTALL)


def _has_no_extractable_content(doc: SourceDocument, body: str) -> bool:
    """LLM 호출 없이도 핵심 주장이 없음이 확실한 문서를 걸러낸다 (토큰/비용 절약).

    2026-08 수동 backlog 분석(382건, Anthropic API 크레딧 소진으로 Claude Code가 직접
    추출) 실측 기준: content_capture.mode가 metadata_only인 문서(DART 자사주 신탁계약
    체결/해지, 실적과 무관한 SEC 6-K/8-K 등 원문 자체가 캡처되지 않은 절차적 공시)는
    100% 핵심 주장 0건이었고, `_ZERO_CONTENT_MARKERS`에 매칭되는 랭킹 다이제스트나
    `## 원문` 섹션 본문이 비어 있는(이미지/동영상 전용) 게시물도 마찬가지였다. 이런
    패턴은 LLM에 보내지 않고 바로 claims=[]로 처리해 실제 콘텐츠가 있는 문서에만 토큰을
    쓴다.
    """
    if doc.content_capture.mode == ContentCaptureMode.METADATA_ONLY:
        return True
    if any(marker in body for marker in _ZERO_CONTENT_MARKERS):
        return True
    match = _RAW_SECTION_RE.search(body)
    if match is not None and not match.group(1).strip():
        return True
    return False


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
    large_doc_client: AnthropicClient | None = None,
    large_doc_char_threshold: int = 50_000,
    batch_size: int = DEFAULT_BATCH_SIZE,
    batch_char_limit: int = DEFAULT_BATCH_CHAR_LIMIT,
) -> AnalyzeResult:
    """미분석 문서에 LLM 핵심 주장 추출을 실행한다.

    large_doc_client가 주어지면, 본문 길이가 large_doc_char_threshold를 넘는 문서는 그
    (보통 더 저렴한) 모델로 돌린다 - SEC 10-K/10-Q 전문 캡처(글자 제한 제거) 이후 대형
    문서 하나가 하루 LLM 예산을 통째로 잡아먹는 것을 막기 위함이다. 지정하지 않으면 모든
    문서를 기본 client로 처리한다(기존 동작과 동일).

    두 단계로 LLM 호출 비용을 줄인다:
    1) `_has_no_extractable_content`로 걸러지는 문서(절차적 공시, 링크 다이제스트 등)는
       LLM을 아예 부르지 않고 claims=[]로 바로 처리한다 - 예산 여부와 무관하게 항상 적용
       (비용이 0이므로 예산에 막힐 이유가 없다).
    2) 남은 "작은" 문서(large_doc_char_threshold 이하)는 즉시 개별 호출하지 않고 최대
       batch_size개 / batch_char_limit자까지 모았다가 `extract_claims_batch`로 한 번에
       처리한다 - 문서별 고정 프롬프트/스키마 오버헤드를 문서 수만큼 나눠 낸다. 배치 호출이
       스키마 검증에 실패하면(모델이 일부 document_id를 누락하는 등) 그 배치만 문서별 개별
       호출로 폴백해 전체가 유실되지 않게 한다. 대형 문서는 기존과 동일하게 개별 처리한다.
    """
    processed = 0
    errors: list[str] = []
    extractions: dict[str, ExtractionResult] = {}
    digest: list[ClaimDigestEntry] = []
    pending_small: list[tuple[SourceDocument, str]] = []

    def _finalize(
        doc: SourceDocument, body: str, extraction: ExtractionResult, model_name: str
    ) -> None:
        nonlocal processed
        spliced_body = splice_claims_into_body(body, extraction)
        updated_doc = doc.model_copy(
            update={
                "llm_processed": True,
                "llm_model": model_name,
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

    def _process_single(doc: SourceDocument, body: str) -> None:
        try:
            outcome = extract_claims(client, document_body=body, system_prompt=system_prompt)
            cost_tracker.record_usage(
                client.model, outcome.usage.input_tokens, outcome.usage.output_tokens
            )
            _finalize(doc, body, outcome.result, client.model)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{doc.id}: {exc}")

    def _flush_pending_small() -> None:
        nonlocal pending_small
        if not pending_small:
            return
        if len(pending_small) == 1:
            doc, body = pending_small[0]
            _process_single(doc, body)
        else:
            batch = list(pending_small)
            try:
                outcome = extract_claims_batch(
                    client,
                    documents=[(doc.id, body) for doc, body in batch],
                    system_prompt=system_prompt,
                )
                cost_tracker.record_usage(
                    client.model, outcome.usage.input_tokens, outcome.usage.output_tokens
                )
                for doc, body in batch:
                    _finalize(doc, body, outcome.results[doc.id], client.model)
            except Exception as exc:  # noqa: BLE001
                # 배치 전체가 스키마 검증 등으로 실패해도 문서별 개별 호출로 폴백해
                # 이 배치에 모인 문서들이 통째로 유실되지 않게 한다.
                errors.append(
                    f"batch of {len(batch)} documents fell back to individual calls: {exc}"
                )
                for doc, body in batch:
                    _process_single(doc, body)
        pending_small = []

    budget_exhausted = False
    for file_path in find_unprocessed_document_paths(conn, portfolio_tickers=portfolio_tickers):
        try:
            doc, body = read_document(Path(file_path))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{file_path}: {exc}")
            continue

        if _has_no_extractable_content(doc, body):
            _finalize(doc, body, ExtractionResult(claims=[]), RULE_BASED_SKIP_MODEL_TAG)
            continue

        if budget_exhausted:
            continue
        if not cost_tracker.is_within_budget():
            budget_exhausted = True
            continue

        if large_doc_client is not None and len(body) > large_doc_char_threshold:
            try:
                outcome = extract_claims(
                    large_doc_client, document_body=body, system_prompt=system_prompt
                )
                cost_tracker.record_usage(
                    large_doc_client.model,
                    outcome.usage.input_tokens,
                    outcome.usage.output_tokens,
                )
                _finalize(doc, body, outcome.result, large_doc_client.model)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{file_path}: {exc}")
            continue

        pending_small.append((doc, body))
        pending_chars = sum(len(b) for _, b in pending_small)
        if len(pending_small) >= batch_size or pending_chars >= batch_char_limit:
            _flush_pending_small()

    _flush_pending_small()

    digest.sort(key=lambda entry: entry.published_at, reverse=True)
    return AnalyzeResult(processed=processed, errors=errors, extractions=extractions, digest=digest)

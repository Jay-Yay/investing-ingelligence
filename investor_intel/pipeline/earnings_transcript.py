from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.earnings_transcript_web import (
    EarningsTranscriptError,
    collect_earnings_transcript_web,
)
from investor_intel.collectors.sec_client import SECClient
from investor_intel.collectors.sec_filings_parser import parse_company_filings
from investor_intel.llm.client import AnthropicClient
from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.models.common import SourceType
from investor_intel.models.config import CompanyConfig
from investor_intel.pipeline.collect import persist_collect_result
from investor_intel.storage.sqlite_index import has_transcript_for_period

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

_REGULAR_FORMS = frozenset({"10-K", "10-Q"})
_FPI_FORMS = frozenset({"20-F", "6-K"})


@dataclass
class EarningsTranscriptRunResult:
    persisted: int = 0
    errors: list[str] = field(default_factory=list)


def _target_reporting_period(sec_client: SECClient, company: CompanyConfig) -> date | None:
    """이 회사의 가장 최근 정기보고서(10-K/10-Q, FPI는 20-F/6-K) period_of_report를 "지금
    녹취록을 채워야 할 분기"로 삼는다. 회사 재무 캘린더를 별도로 추정하지 않고 이미 SEC가
    공개한 정기보고서 메타데이터를 그대로 앵커로 쓴다 - 새 분기가 정기보고서로 공시되기
    전까지는 새 타깃이 생기지 않는다(정기보고서보다 컨퍼런스콜이 먼저 나오는 경우 한 박자
    늦게 잡히지만, 기존 8-K exhibit 스캔도 8-K 공시 자체가 있어야 잡히므로 새로운 지연은
    아니다).

    FPI의 6-K는 배당공지 등 실적과 무관한 공시도 섞여 있다 - period_of_report가 채워진
    6-K만 "분기 실적 관련"으로 간주하는 휴리스틱을 쓴다(실적 무관 6-K는 대체로 이 필드가
    비어 있다는 관찰에 기반 - 완벽하지 않을 수 있어 실제 데이터로 추가 검증이 필요하다).
    """
    forms = _FPI_FORMS if company.is_foreign_private_issuer else _REGULAR_FORMS
    submissions = sec_client.get_json(_SUBMISSIONS_URL.format(cik=company.cik))
    filings = parse_company_filings(submissions, forms=forms)
    candidates = [f for f in filings if f.period_of_report is not None]
    if not candidates:
        return None
    latest = max(candidates, key=lambda f: f.filing_date)
    return latest.period_of_report


def run_earnings_transcript_collection(
    companies: list[CompanyConfig],
    sec_client: SECClient,
    anthropic_client: AnthropicClient,
    cost_tracker: CostTracker,
    checkpoint_store: CheckpointStore,
    vault_path: Path,
    conn: sqlite3.Connection,
) -> EarningsTranscriptRunResult:
    """SEC 8-K exhibit 스캔(sec_document_fetch.find_transcript_exhibit)이 놓치는 실적발표
    컨퍼런스콜 갭을 회사별 web_search 기반 보완 검색으로 채운다
    (collectors/earnings_transcript_web.py). run_daily의 analyze 이후, web_research과 같은
    단계에서 호출되며 LLM 주장 추출/판단은 하지 않는다(scrape only) - 저장된 문서는
    llm_processed=false로 남아 다음 analyze 실행에서 다른 문서와 동일하게 처리된다.
    """
    result = EarningsTranscriptRunResult()
    for company in companies:
        if not cost_tracker.is_within_budget():
            result.errors.append("LLM 예산 초과 - 컨퍼런스콜 웹서치 중단")
            break

        source_id = f"earnings_transcript_web_{company.ticker.lower()}"
        try:
            target_period = _target_reporting_period(sec_client, company)
        except Exception as exc:  # noqa: BLE001 - 회사 하나 실패해도 나머지는 계속 진행
            result.errors.append(f"{company.ticker}: 대상 분기 조회 실패: {exc}")
            continue

        if target_period is None:
            continue

        period_label = target_period.isoformat()
        state = checkpoint_store.get_state(source_id)
        if state.last_seen_id == period_label:
            continue

        if has_transcript_for_period(conn, company.ticker, period_label):
            # SEC 8-K exhibit 스캔이 이미 이 분기의 진짜 녹취록을 찾아뒀다 - 중복 LLM 호출 없이
            # 체크포인트만 이 분기로 전진시킨다.
            checkpoint_store.record_success(source_id, last_seen_id=period_label)
            continue

        try:
            collect_result, input_tokens, output_tokens = collect_earnings_transcript_web(
                anthropic_client, company.ticker, company.name, target_period
            )
            cost_tracker.record_usage(anthropic_client.model, input_tokens, output_tokens)
        except EarningsTranscriptError as exc:
            result.errors.append(f"{company.ticker}: {exc}")
            checkpoint_store.record_failure(source_id)
            continue
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{company.ticker}: 컨퍼런스콜 웹서치 실패: {exc}")
            checkpoint_store.record_failure(source_id)
            continue

        if collect_result is None:
            # 검색했지만 못 찾음 - 진짜 오류가 아니라 유효한 빈 결과다. 이 분기를 처리 완료로
            # 기록해두지 않으면, 끝내 전문이 존재하지 않는 회사를 매 실행마다 같은 검색으로
            # 재시도해 비용이 무한 누적된다. 뒤늦게 게시된 녹취록을 다시 채우고 싶으면(기존
            # `collect --backfill`처럼) 체크포인트를 우회하는 수동 재처리가 필요하다.
            checkpoint_store.record_success(source_id, last_seen_id=period_label)
            continue

        persist_result = persist_collect_result(
            collect_result, SourceType.EARNINGS_TRANSCRIPT, company.ticker, vault_path, conn
        )
        result.persisted += persist_result.count
        result.errors.extend(persist_result.errors)
        checkpoint_store.record_success(source_id, last_seen_id=period_label)

    return result

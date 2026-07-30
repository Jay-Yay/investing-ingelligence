from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from investor_intel.collectors.web_research import collect_web_research
from investor_intel.llm.client import AnthropicClient
from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.models.common import SourceType
from investor_intel.models.portfolio import Position
from investor_intel.pipeline.collect import persist_collect_result
from investor_intel.storage.content_hash import compute_stable_id
from investor_intel.storage.sqlite_index import get_document_by_id


@dataclass
class WebResearchRunResult:
    persisted: int = 0
    errors: list[str] = field(default_factory=list)


def _already_scraped_today(conn: sqlite3.Connection, symbol: str) -> bool:
    """오늘자 해당 symbol의 web_search 문서가 이미 (다른 머신에서) 저장돼 있는지 확인한다.

    collect_web_research()의 source_specific_id 규칙(f"{symbol}-{today}")과 동일한 키로
    stable_id를 재계산한다 - 이 함수를 collect_web_research 호출 "전"에 불러 이미 있으면
    LLM 웹서치 호출 자체를 건너뛴다(비용 절감 + Mac1/Mac2가 같은 날 서로 다른 검색
    결과를 같은 파일 경로에 덮어써 git merge 충돌을 일으키는 것도 방지).
    """
    today = datetime.now(UTC).date().isoformat()
    stable_id = compute_stable_id(
        SourceType.WEB_SEARCH.value,
        symbol,
        f"{symbol}-{today}",
        f"web-search://{symbol}/{today}",
    )
    return get_document_by_id(conn, stable_id) is not None


def run_web_research_for_portfolio(
    positions: list[Position],
    client: AnthropicClient,
    cost_tracker: CostTracker,
    vault_path: Path,
    conn: sqlite3.Connection,
) -> WebResearchRunResult:
    """보유 종목별로 실시간 웹 검색 결과를 스크랩해 vault에 저장한다 (LLM 주장 추출/판단 없이).

    vault 스크랩 소스(네이버/텔레그램/공시 등)만으로는 놓치는 정보(예: 해외 헤지펀드 13G/13F
    공시, 외신 보도)를 보완하기 위한 단계 - 종목별 폴더(10_Sources/WebSearch/<symbol>/)에
    날짜별로 저장한다. 이번 실행의 analyze는 이미 끝난 뒤 호출되므로, 오늘 저장된 문서는
    오늘의 claims_summary/포트폴리오 모니터 입력에는 포함되지 않고 다음 analyze 실행부터
    일반 문서와 동일하게 처리된다.
    """
    result = WebResearchRunResult()
    for position in positions:
        if not cost_tracker.is_within_budget():
            result.errors.append("LLM 예산 초과 - 웹 검색 스크랩 중단")
            break
        if _already_scraped_today(conn, position.symbol):
            continue
        try:
            collect_result, input_tokens, output_tokens = collect_web_research(
                client, position.symbol, position.name
            )
            cost_tracker.record_usage(client.model, input_tokens, output_tokens)
            persist_result = persist_collect_result(
                collect_result, SourceType.WEB_SEARCH, position.symbol, vault_path, conn
            )
            result.persisted += persist_result.count
            result.errors.extend(persist_result.errors)
        except Exception as exc:  # noqa: BLE001 - 종목 하나 실패해도 나머지는 계속 진행
            result.errors.append(f"{position.symbol}: 웹 검색 스크랩 실패: {exc}")
    return result

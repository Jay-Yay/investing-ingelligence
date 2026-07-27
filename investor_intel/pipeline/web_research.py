from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from investor_intel.collectors.web_research import collect_web_research
from investor_intel.llm.client import AnthropicClient
from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.models.common import SourceType
from investor_intel.models.portfolio import Position
from investor_intel.pipeline.collect import persist_collect_result


@dataclass
class WebResearchRunResult:
    persisted: int = 0
    errors: list[str] = field(default_factory=list)


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

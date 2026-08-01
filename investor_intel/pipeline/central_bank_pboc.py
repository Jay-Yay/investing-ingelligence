from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.central_bank_pboc_web import (
    PbocMpcWebError,
    collect_pboc_mpc_web,
)
from investor_intel.llm.client import AnthropicClient
from investor_intel.llm.cost_tracker import CostTracker
from investor_intel.models.common import SourceType
from investor_intel.pipeline.collect import persist_collect_result

_SOURCE_ID = "central_bank_pboc_mpc"


@dataclass
class PbocMpcRunResult:
    persisted: int = 0
    errors: list[str] = field(default_factory=list)


def _current_quarter_label(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    quarter = (now.month - 1) // 3 + 1
    return f"{now.year}Q{quarter}"


def run_pboc_mpc_collection(
    anthropic_client: AnthropicClient,
    cost_tracker: CostTracker,
    checkpoint_store: CheckpointStore,
    vault_path: Path,
    conn: sqlite3.Connection,
) -> PbocMpcRunResult:
    """PBOC 통화정책위원회 분기 정례회의 공보를 web_search로 찾아 vault에 저장한다.

    PBOC는 분기(~3개월)마다 한 번만 정례회의를 열므로, 이번 분기에 이미 시도했으면(찾았든
    못 찾았든) 재시도하지 않는다 - earnings_transcript.py의 분기별 체크포인트와 동일한 이유
    (무한 재시도로 LLM 예산이 새는 것 방지).
    """
    result = PbocMpcRunResult()
    quarter_label = _current_quarter_label()
    state = checkpoint_store.get_state(_SOURCE_ID)
    if state.last_seen_id == quarter_label:
        return result

    try:
        collect_result, input_tokens, output_tokens = collect_pboc_mpc_web(
            anthropic_client, quarter_label
        )
        cost_tracker.record_usage(anthropic_client.model, input_tokens, output_tokens)
    except PbocMpcWebError as exc:
        result.errors.append(f"PBOC MPC 웹서치 실패: {exc}")
        checkpoint_store.record_failure(_SOURCE_ID)
        return result
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"PBOC MPC 웹서치 실패: {exc}")
        checkpoint_store.record_failure(_SOURCE_ID)
        return result

    if collect_result is None:
        # 검색했지만 이번 분기 공보를 못 찾음 - 유효한 빈 결과. 체크포인트를 전진시켜 매
        # 실행마다 같은 검색을 반복하지 않게 한다.
        checkpoint_store.record_success(_SOURCE_ID, last_seen_id=quarter_label)
        return result

    persist_result = persist_collect_result(
        collect_result, SourceType.CENTRAL_BANK, "pboc", vault_path, conn
    )
    result.persisted += persist_result.count
    result.errors.extend(persist_result.errors)
    checkpoint_store.record_success(_SOURCE_ID, last_seen_id=quarter_label)
    return result

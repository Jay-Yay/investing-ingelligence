from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from investor_intel.storage.cost_ledger import record_usage, sum_cost_between

_PRICING_USD_PER_MILLION_TOKENS: dict[str, dict[str, float]] = {
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}


# Message Batches API는 입력/출력 토큰이 전 구간 50% 할인이다. llm_usage 테이블에는 실제
# 청구액이 남아야 예산 판정(is_within_budget)이 현실과 맞으므로 여기서 반영한다.
BATCH_DISCOUNT = 0.5


class UnknownModelPricingError(Exception):
    pass


def compute_cost_usd(
    model: str, input_tokens: int, output_tokens: int, batch: bool = False
) -> float:
    pricing = _PRICING_USD_PER_MILLION_TOKENS.get(model)
    if pricing is None:
        raise UnknownModelPricingError(f"no pricing table entry for model {model!r}")
    cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
    return cost * BATCH_DISCOUNT if batch else cost


class CostTracker:
    def __init__(
        self,
        conn: sqlite3.Connection,
        daily_budget_usd: float,
        monthly_budget_usd: float,
        timezone: str = "Asia/Seoul",
    ) -> None:
        self._conn = conn
        self._daily_budget_usd = daily_budget_usd
        self._monthly_budget_usd = monthly_budget_usd
        self._zone = ZoneInfo(timezone)

    def record_usage(
        self, model: str, input_tokens: int, output_tokens: int, batch: bool = False
    ) -> float:
        cost = compute_cost_usd(model, input_tokens, output_tokens, batch=batch)
        record_usage(
            self._conn,
            timestamp=datetime.now(UTC),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        return cost

    def daily_total_usd(self) -> float:
        now_local = datetime.now(self._zone)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        return sum_cost_between(self._conn, start_local.astimezone(UTC), end_local.astimezone(UTC))

    def monthly_total_usd(self) -> float:
        now_local = datetime.now(self._zone)
        start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start_local.month == 12:
            end_local = start_local.replace(year=start_local.year + 1, month=1)
        else:
            end_local = start_local.replace(month=start_local.month + 1)
        return sum_cost_between(self._conn, start_local.astimezone(UTC), end_local.astimezone(UTC))

    def is_within_budget(self) -> bool:
        return (
            self.daily_total_usd() < self._daily_budget_usd
            and self.monthly_total_usd() < self._monthly_budget_usd
        )

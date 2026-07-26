from __future__ import annotations

from datetime import date, timedelta

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.naver_research_common import build_research_collect_item
from investor_intel.collectors.naver_research_parser import NaverResearchStub, parse_weekly_hot_list
from investor_intel.models.config import SourceConfig

LIST_URL = "https://stock.naver.com/api/stockSecurity/researches/v2/weekly-hot"
_MAX_LOOKBACK_DAYS = 7
_RANK_SIZE = 10


class NaverWeeklyHotCollector:
    """"요즘 많이 보는 리포트" (조회수 기준 주간 인기 Top 10) - a ranking snapshot, not a
    chronological feed, so unlike NaverResearchCollector this always re-fetches and re-attempts
    all current top-N items every run instead of walking a "new since last checkpoint" window.
    Rankings reshuffle day to day (an item can re-enter after dropping out), so a checkpoint-based
    cutoff would miss re-entries; instead this relies on persist_collect_result's existing
    duplicate detection (by source_specific_id) to silently skip items already in the vault and
    only write ones that are genuinely new."""

    def __init__(
        self,
        source: SourceConfig,
        client: SimpleHttpClient,
        checkpoint_store: CheckpointStore,
    ) -> None:
        self.source_id = source.id
        self._source = source
        self._client = client
        self._checkpoint_store = checkpoint_store

    def _fetch_current_ranking(self) -> list[NaverResearchStub]:
        # the API returns an empty researchList for dates too close to today (today itself, and
        # weekend dates before enough view data has accumulated) - walk backwards until a
        # non-empty snapshot is found rather than hardcoding a market calendar.
        for offset in range(_MAX_LOOKBACK_DAYS):
            start_date = date.today() - timedelta(days=offset)
            json_text = self._client.get_text(
                f"{LIST_URL}?startDate={start_date.isoformat()}&size={_RANK_SIZE}"
            )
            stubs = parse_weekly_hot_list(json_text)
            if stubs:
                return stubs
        return []

    def _build_item(self, stub: NaverResearchStub) -> CollectItem:
        return build_research_collect_item(self._client, stub, self._source.name)

    def _collect(self, stubs: list[NaverResearchStub]) -> CollectResult:
        items: list[CollectItem] = []
        errors: list[str] = []
        for stub in stubs:
            try:
                items.append(self._build_item(stub))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{stub.research_id}: {exc}")

        if items:
            self._checkpoint_store.record_success(
                self.source_id, last_seen_id=str(stubs[0].research_id)
            )
        elif errors:
            self._checkpoint_store.record_failure(self.source_id)

        return CollectResult(
            source_id=self.source_id,
            success=not errors,
            items=items,
            errors=errors,
            new_count=len(items),
        )

    def backfill(self, days: int) -> CollectResult:
        # "backfill N days" doesn't map onto a ranking snapshot - there's only ever a current
        # top 10, so this is identical to collect_incremental().
        result = self._collect(self._fetch_current_ranking())
        state = self._checkpoint_store.get_state(self.source_id)
        state.backfill_completed = True
        self._checkpoint_store.save_state(state)
        return result

    def collect_incremental(self) -> CollectResult:
        return self._collect(self._fetch_current_ranking())

from __future__ import annotations

from datetime import date, timedelta

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.naver_research_common import build_research_collect_item
from investor_intel.collectors.naver_research_parser import (
    NaverResearchStub,
    parse_naver_research_list,
)
from investor_intel.models.config import SourceConfig

LIST_URL = "https://m.stock.naver.com/api/research/company"

# 안전장치: backfill이 날짜 파싱 실패 등으로 cutoff에 영영 도달하지 못해도 무한 루프를 돌지
# 않도록 페이지 수 상한을 둔다. 페이지당 약 20건, 실측상 월 평균 약 40페이지이므로 2000페이지면
# 수년치 백필도 넉넉히 커버한다.
_MAX_BACKFILL_PAGES = 2000


class NaverResearchCollector:
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

    def _fetch_page(self, page: int) -> list[NaverResearchStub]:
        # 1페이지는 쿼리스트링 없이 호출한다 (기존 목록 API 호출부와 동일한 URL을 유지해 캐시/
        # 테스트 호환성을 지킨다) - 네이버 API가 page 파라미터 없이도 1페이지와 동일한 결과를
        # 돌려준다.
        url = LIST_URL if page <= 1 else f"{LIST_URL}?page={page}"
        json_text = self._client.get_text(url)
        return parse_naver_research_list(json_text)

    def _fetch_all_stubs(self) -> list[NaverResearchStub]:
        return self._fetch_page(1)

    def _fetch_stubs_until_cutoff(self, cutoff: date) -> list[NaverResearchStub]:
        all_stubs: list[NaverResearchStub] = []
        for page in range(1, _MAX_BACKFILL_PAGES + 1):
            stubs = self._fetch_page(page)
            if not stubs:
                break
            all_stubs.extend(stubs)
            # 목록은 최신순이므로 이 페이지의 가장 오래된 항목이 이미 cutoff보다 오래됐으면
            # 더 이전 페이지를 볼 필요가 없다. write_date가 없는(파싱 실패) 항목은 "아직 모른다"로
            # 취급해 루프를 계속 진행시킨다 - 페이지 상한이 최종 안전장치 역할을 한다.
            oldest_on_page = stubs[-1].write_date
            if oldest_on_page is not None and oldest_on_page < cutoff:
                break
        return all_stubs

    def _build_item(self, stub: NaverResearchStub) -> CollectItem:
        return build_research_collect_item(self._client, stub, self._source.name)

    def _collect(
        self, stubs_to_process: list[NaverResearchStub], checkpoint_id: str | None
    ) -> CollectResult:
        items: list[CollectItem] = []
        errors: list[str] = []
        for stub in stubs_to_process:
            try:
                items.append(self._build_item(stub))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{stub.research_id}: {exc}")

        if checkpoint_id is not None:
            self._checkpoint_store.record_success(self.source_id, last_seen_id=checkpoint_id)
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
        cutoff = date.today() - timedelta(days=days)
        all_stubs = self._fetch_stubs_until_cutoff(cutoff)
        to_process = [s for s in all_stubs if (s.write_date or date.today()) >= cutoff]
        checkpoint_id = str(all_stubs[0].research_id) if all_stubs else None
        result = self._collect(to_process, checkpoint_id)
        state = self._checkpoint_store.get_state(self.source_id)
        state.backfill_completed = True
        self._checkpoint_store.save_state(state)
        return result

    def collect_incremental(self) -> CollectResult:
        # newest-first-list-walk: the list is ordered newest-first, so "new since last run" is
        # everything above the previously recorded top item, not a published_at comparison -
        # see IBInsightsCollector.collect_incremental for why.
        all_stubs = self._fetch_all_stubs()
        state = self._checkpoint_store.get_state(self.source_id)

        if state.last_seen_id is None:
            to_process = list(all_stubs)
        else:
            to_process = []
            for stub in all_stubs:
                if str(stub.research_id) == state.last_seen_id:
                    break
                to_process.append(stub)

        checkpoint_id = str(all_stubs[0].research_id) if all_stubs else state.last_seen_id
        return self._collect(to_process, checkpoint_id)

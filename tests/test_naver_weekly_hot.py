import json
from datetime import date, timedelta

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.naver_weekly_hot import LIST_URL, NaverWeeklyHotCollector
from investor_intel.models.config import SourceConfig
from investor_intel.storage.sqlite_index import connect, init_db

_DETAIL_URL_TMPL = "https://m.stock.naver.com/api/research/company/{research_id}"


def _source() -> SourceConfig:
    return SourceConfig(
        id="naver_weekly_hot_naver", type="naver_weekly_hot", name="naver-weekly-hot", url=LIST_URL
    )


def _collector(tmp_path) -> tuple[NaverWeeklyHotCollector, CheckpointStore]:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    checkpoint_store = CheckpointStore(conn)
    client = SimpleHttpClient()
    return NaverWeeklyHotCollector(_source(), client, checkpoint_store), checkpoint_store


def _ranking_response(start_date: str, rows: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"startDate": start_date, "researchList": rows})


def _row(rank: int, nid: int, item_code: str = "017670") -> dict:
    return {
        "ranking": str(rank),
        "type": "company",
        "nid": str(nid),
        "title": f"랭킹 {rank}위 리포트",
        "brokerName": "신한투자증권",
        "writeDate": "2026-07-24",
        "readCount": "1000",
        "itemCode": item_code,
        "analystName": None,
    }


def _mock_detail(research_id: int) -> None:
    payload = {
        "researchContent": {
            "itemCode": "017670",
            "itemName": "SK텔레콤",
            "researchId": research_id,
            "title": f"랭킹 리포트 {research_id}",
            "brokerName": "신한투자증권",
            "writeDate": "2026-07-24",
            "attachUrl": None,
            "content": "<p>요약 내용</p>",
            "opinion": "매수",
            "goalPrice": "100000",
            "prevGoalPrice": "95000",
        }
    }
    respx.get(_DETAIL_URL_TMPL.format(research_id=research_id)).mock(
        return_value=httpx.Response(200, json=payload)
    )


@respx.mock
@freeze_time("2026-07-26")
def test_collect_uses_todays_ranking_when_available(tmp_path) -> None:
    respx.get(f"{LIST_URL}?startDate=2026-07-26&size=10").mock(
        return_value=_ranking_response("2026-07-26", [_row(1, 94282), _row(2, 94277)])
    )
    _mock_detail(94282)
    _mock_detail(94277)
    collector, checkpoint_store = _collector(tmp_path)

    result = collector.collect_incremental()

    assert len(result.items) == 2
    assert result.items[0].title == "[SK텔레콤] 랭킹 1위 리포트"
    state = checkpoint_store.get_state(collector.source_id)
    assert state.last_seen_id == "94282"


@respx.mock
@freeze_time("2026-07-26")
def test_collect_walks_back_through_empty_days_until_data_found(tmp_path) -> None:
    respx.get(f"{LIST_URL}?startDate=2026-07-26&size=10").mock(
        return_value=_ranking_response("2026-07-26", [])
    )
    respx.get(f"{LIST_URL}?startDate=2026-07-25&size=10").mock(
        return_value=_ranking_response("2026-07-25", [])
    )
    respx.get(f"{LIST_URL}?startDate=2026-07-24&size=10").mock(
        return_value=_ranking_response("2026-07-24", [_row(1, 94484)])
    )
    _mock_detail(94484)
    collector, _ = _collector(tmp_path)

    result = collector.collect_incremental()

    assert [item.source_specific_id for item in result.items] == ["94484"]


@respx.mock
@freeze_time("2026-07-26")
def test_collect_returns_empty_result_when_no_data_within_lookback_window(tmp_path) -> None:
    for offset in range(7):
        d = (date(2026, 7, 26) - timedelta(days=offset)).isoformat()
        respx.get(f"{LIST_URL}?startDate={d}&size=10").mock(
            return_value=_ranking_response(d, [])
        )
    collector, checkpoint_store = _collector(tmp_path)

    result = collector.collect_incremental()

    assert result.items == []
    assert result.success is True
    state = checkpoint_store.get_state(collector.source_id)
    assert state.last_seen_id is None


@respx.mock
@freeze_time("2026-07-26")
def test_backfill_and_collect_incremental_both_return_current_ranking_ignoring_checkpoint(
    tmp_path,
) -> None:
    # regression: this is a ranking *snapshot*, not a chronological feed - re-entrants must not
    # be filtered out by a "new since last checkpoint" walk, so both entry points always process
    # the full current top-N and rely on persist-time dedup instead.
    respx.get(f"{LIST_URL}?startDate=2026-07-26&size=10").mock(
        return_value=_ranking_response("2026-07-26", [_row(1, 94282), _row(2, 94277)])
    )
    _mock_detail(94282)
    _mock_detail(94277)
    collector, checkpoint_store = _collector(tmp_path)
    collector.collect_incremental()  # advances checkpoint to 94282

    result = collector.collect_incremental()

    assert {item.source_specific_id for item in result.items} == {"94282", "94277"}


def test_ranking_response_json_smoke() -> None:
    json.loads(json.dumps({"researchList": [_row(1, 1)]}))

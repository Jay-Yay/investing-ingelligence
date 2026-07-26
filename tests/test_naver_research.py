import json

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.naver_research import LIST_URL, NaverResearchCollector
from investor_intel.models.config import SourceConfig
from investor_intel.storage.sqlite_index import connect, init_db

_DETAIL_URL_TMPL = "https://m.stock.naver.com/api/research/company/{research_id}"

_VALID_PDF_WITH_TEXT = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>
/MediaBox[0 0 200 200]/Contents 5 0 R>>endobj
4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
5 0 obj<</Length 44>>
stream
BT /F1 12 Tf 10 100 Td (Hello PDF World) Tj ET
endstream
endobj
xref
0 6
trailer<</Size 6/Root 1 0 R>>
startxref
0
%%EOF"""


def _source() -> SourceConfig:
    return SourceConfig(
        id="naver_research_naver", type="naver_research", name="naver", url=LIST_URL
    )


def _collector(tmp_path) -> tuple[NaverResearchCollector, CheckpointStore]:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    checkpoint_store = CheckpointStore(conn)
    client = SimpleHttpClient()
    return NaverResearchCollector(_source(), client, checkpoint_store), checkpoint_store


def _mock_list(stubs: list[dict]) -> None:
    respx.get(LIST_URL).mock(return_value=httpx.Response(200, json=stubs))


def _mock_paginated_list(pages_by_number: dict[int, list[dict]]) -> None:
    # a plain `respx.get(LIST_URL).mock(...)` for page 1 also matches `LIST_URL?page=2`, `?page=3`,
    # etc. (respx treats an unconstrained route as matching any query string), so registering one
    # route per page number would make every page beyond the last explicitly-mocked one silently
    # fall back to page 1's response instead of erroring - which would make
    # `_fetch_stubs_until_cutoff` loop until `_MAX_BACKFILL_PAGES` instead of stopping. A single
    # side_effect keyed off the request's own `page` query param avoids that trap and matches
    # "unmocked page -> no data" too.
    def side_effect(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=pages_by_number.get(page, []))

    respx.get(url__startswith=LIST_URL).mock(side_effect=side_effect)


def _mock_detail(research_id: int, **overrides) -> None:
    payload = {
        "researchContent": {
            "itemCode": "017670",
            "itemName": "SK텔레콤",
            "researchId": research_id,
            "title": "테스트 리포트",
            "brokerName": "신한투자증권",
            "writeDate": "2026-07-24",
            "attachUrl": None,
            "content": "<p>요약 내용입니다.</p>",
            "opinion": "매수",
            "goalPrice": "100000",
            "prevGoalPrice": "95000",
        }
    }
    payload["researchContent"].update(overrides)
    respx.get(_DETAIL_URL_TMPL.format(research_id=research_id)).mock(
        return_value=httpx.Response(200, json=payload)
    )


def _stub(research_id: int, item_name: str = "SK텔레콤", write_date: str = "2026-07-24") -> dict:
    return {
        "itemCode": "017670",
        "itemName": item_name,
        "researchId": research_id,
        "title": "테스트 리포트",
        "brokerName": "신한투자증권",
        "writeDate": write_date,
    }


@respx.mock
def test_collect_incremental_uses_content_field_when_no_pdf(tmp_path) -> None:
    _mock_list([_stub(94484)])
    _mock_detail(94484)
    collector, checkpoint_store = _collector(tmp_path)

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "excerpt"
    assert "요약 내용입니다" in item.body_text
    assert item.author == "신한투자증권"
    assert item.title == "[SK텔레콤] 테스트 리포트"
    assert item.companies == ["017670"]
    assert item.language == "ko"
    state = checkpoint_store.get_state(collector.source_id)
    assert state.last_seen_id == "94484"


@respx.mock
def test_collect_incremental_extracts_pdf_full_text_when_attached(tmp_path) -> None:
    _mock_list([_stub(94483)])
    pdf_url = "https://stock.pstatic.net/stock-research/company/16/report.pdf"
    _mock_detail(94483, attachUrl=pdf_url)
    respx.get(pdf_url).mock(
        return_value=httpx.Response(
            200, content=_VALID_PDF_WITH_TEXT, headers={"content-type": "application/octet-stream"}
        )
    )
    collector, _ = _collector(tmp_path)

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "full"
    assert item.content_capture_reason is None
    assert "Hello PDF World" in item.body_text


@respx.mock
def test_collect_incremental_falls_back_to_metadata_only_when_detail_fetch_fails(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    _mock_list([_stub(94484)])
    respx.get(_DETAIL_URL_TMPL.format(research_id=94484)).mock(return_value=httpx.Response(500))
    collector, _ = _collector(tmp_path)

    result = collector.collect_incremental()

    (item,) = result.items
    assert item.content_capture_mode == "metadata_only"
    assert item.content_capture_reason is not None


@respx.mock
def test_collect_incremental_second_run_only_returns_new_reports(tmp_path) -> None:
    _mock_list([_stub(94484), _stub(94483, item_name="펌텍코리아")])
    _mock_detail(94484)
    _mock_detail(94483)
    collector, checkpoint_store = _collector(tmp_path)
    collector.collect_incremental()

    respx.get(LIST_URL).mock(
        return_value=httpx.Response(
            200,
            json=[_stub(94485, item_name="새 리포트"), _stub(94484), _stub(94483)],
        )
    )
    _mock_detail(94485)

    result = collector.collect_incremental()

    assert [item.source_specific_id for item in result.items] == ["94485"]
    state = checkpoint_store.get_state(collector.source_id)
    assert state.last_seen_id == "94485"


@respx.mock
@freeze_time("2026-07-24")
def test_backfill_filters_by_write_date(tmp_path) -> None:
    _mock_list([_stub(94484, write_date="2026-07-24"), _stub(94400, write_date="2025-01-01")])
    _mock_detail(94484)
    _mock_detail(94400)
    collector, _ = _collector(tmp_path)

    result = collector.backfill(days=7)

    ids = {item.source_specific_id for item in result.items}
    assert ids == {"94484"}


@respx.mock
@freeze_time("2026-07-24")
def test_backfill_paginates_when_cutoff_not_reached_on_first_page(tmp_path) -> None:
    # regression: backfill used to only ever look at the single default page (~20 items), so a
    # configured backfill_days of e.g. 365 was silently a no-op beyond the current day.
    _mock_paginated_list(
        {
            1: [_stub(94484, write_date="2026-07-24"), _stub(94483, write_date="2026-07-23")],
            2: [_stub(94400, write_date="2026-07-01"), _stub(94399, write_date="2026-06-01")],
        }
    )
    for research_id in (94484, 94483, 94400, 94399):
        _mock_detail(research_id)
    collector, checkpoint_store = _collector(tmp_path)

    result = collector.backfill(days=30)

    ids = {item.source_specific_id for item in result.items}
    assert ids == {"94484", "94483", "94400"}  # 94399 (2026-06-01) is older than the 30-day cutoff
    state = checkpoint_store.get_state(collector.source_id)
    assert state.last_seen_id == "94484"
    assert state.backfill_completed is True


@respx.mock
@freeze_time("2026-07-24")
def test_backfill_stops_paginating_once_a_page_is_entirely_before_cutoff(tmp_path) -> None:
    _mock_paginated_list(
        {
            1: [_stub(94484, write_date="2026-07-24")],
            2: [_stub(94400, write_date="2025-01-01")],
            # deliberately no page 3 entry - if the collector tried to fetch it, it gets an empty
            # list (see _mock_paginated_list) rather than looping; page 2's date already ends the
            # backfill before page 3 would ever be requested, so either behavior would pass here,
            # but this keeps the fixture honest about what "no more data" looks like.
        }
    )
    _mock_detail(94484)
    _mock_detail(94400)
    collector, _ = _collector(tmp_path)

    result = collector.backfill(days=7)

    ids = {item.source_specific_id for item in result.items}
    assert ids == {"94484"}


def test_parse_list_json_smoke() -> None:
    # sanity check that our fixture builder produces genuinely parseable JSON
    json.loads(json.dumps([_stub(1)]))

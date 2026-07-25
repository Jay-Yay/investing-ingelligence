import json

import httpx
import respx

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
def test_backfill_filters_by_write_date(tmp_path) -> None:
    _mock_list([_stub(94484, write_date="2026-07-24"), _stub(94400, write_date="2025-01-01")])
    _mock_detail(94484)
    _mock_detail(94400)
    collector, _ = _collector(tmp_path)

    result = collector.backfill(days=7)

    ids = {item.source_specific_id for item in result.items}
    assert ids == {"94484"}


def test_parse_list_json_smoke() -> None:
    # sanity check that our fixture builder produces genuinely parseable JSON
    json.loads(json.dumps([_stub(1)]))

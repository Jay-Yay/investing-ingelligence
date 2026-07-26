import zipfile
from io import BytesIO
from pathlib import Path

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.dart import DartCollector
from investor_intel.collectors.dart_client import DartClient
from investor_intel.models.config import KoreanCompanyConfig
from investor_intel.storage.sqlite_index import connect, init_db

FIXTURES = Path(__file__).parent / "fixtures" / "dart"

_API_KEY = "test-key"
_BASE = "https://opendart.fss.or.kr/api/list.json"


def _company() -> KoreanCompanyConfig:
    return KoreanCompanyConfig(
        ticker="005930",
        corp_code="00126380",
        name="삼성전자",
        report_types=["A", "B"],
    )


def _mock_list_routes() -> None:
    respx.get(
        f"{_BASE}?crtfc_key={_API_KEY}&corp_code=00126380&bgn_de=19990101"
        "&end_de=20240601&pblntf_ty=A&page_no=1&page_count=100"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "list_type_a.json").read_text(encoding="utf-8")
        )
    )
    respx.get(
        f"{_BASE}?crtfc_key={_API_KEY}&corp_code=00126380&bgn_de=19990101"
        "&end_de=20240601&pblntf_ty=B&page_no=1&page_count=100"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "list_type_b.json").read_text(encoding="utf-8")
        )
    )


@respx.mock
@freeze_time("2024-06-01")
def test_backfill_returns_only_in_window_filing(tmp_path) -> None:
    _mock_list_routes()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = DartClient(api_key=_API_KEY)
    collector = DartCollector(_company(), client, CheckpointStore(conn), api_key=_API_KEY)

    result = collector.backfill(days=62)
    client.close()

    assert result.success
    assert result.new_count == 1
    item = result.items[0]
    assert item.accession_number == "20240401000002"
    assert item.reporting_period == "2024-04-01"
    assert item.language == "ko"
    assert item.content_capture_mode == "metadata_only"


@respx.mock
@freeze_time("2024-06-01")
def test_collect_incremental_dedupes_across_report_types_and_is_idempotent(tmp_path) -> None:
    _mock_list_routes()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = DartClient(api_key=_API_KEY)
    checkpoint_store = CheckpointStore(conn)

    first_collector = DartCollector(_company(), client, checkpoint_store, api_key=_API_KEY)
    first_result = first_collector.collect_incremental()
    # 3 unique rcept_no across type A (2) + type B (2), one overlapping
    assert first_result.new_count == 3
    accession_numbers = {item.accession_number for item in first_result.items}
    assert accession_numbers == {"20240301000000", "20240315000001", "20240401000002"}

    second_collector = DartCollector(_company(), client, checkpoint_store, api_key=_API_KEY)
    second_result = second_collector.collect_incremental()
    client.close()

    assert second_result.new_count == 0
    assert second_result.items == []


def _document_zip_bytes(xml_text: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("doc.xml", xml_text)
    return buffer.getvalue()


@respx.mock
@freeze_time("2024-06-01")
def test_annual_report_captures_full_text_and_tags_title(tmp_path) -> None:
    _mock_list_routes()
    respx.get(
        f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={_API_KEY}"
        "&rcept_no=20240315000001"
    ).mock(
        return_value=httpx.Response(
            200,
            content=_document_zip_bytes(
                "<DOCUMENT><TITLE>사업보고서</TITLE><BODY><P>테스트 본문</P></BODY></DOCUMENT>"
            ),
        )
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = DartClient(api_key=_API_KEY)
    collector = DartCollector(_company(), client, CheckpointStore(conn), api_key=_API_KEY)

    result = collector.collect_incremental()
    client.close()

    annual = next(item for item in result.items if item.accession_number == "20240315000001")
    assert annual.title.startswith("[연간보고서] ")
    assert annual.content_capture_mode == "full"
    assert "테스트 본문" in annual.body_text


@respx.mock
@freeze_time("2024-06-01")
def test_non_periodic_report_stays_metadata_only(tmp_path) -> None:
    _mock_list_routes()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = DartClient(api_key=_API_KEY)
    collector = DartCollector(_company(), client, CheckpointStore(conn), api_key=_API_KEY)

    result = collector.collect_incremental()
    client.close()

    major_report = next(
        item for item in result.items if item.accession_number == "20240401000002"
    )
    assert major_report.content_capture_mode == "metadata_only"
    assert not major_report.title.startswith("[")


@respx.mock
@freeze_time("2024-06-01")
def test_source_id_includes_ticker(tmp_path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = DartClient(api_key=_API_KEY)
    collector = DartCollector(_company(), client, CheckpointStore(conn), api_key=_API_KEY)
    client.close()
    assert collector.source_id == "dart_005930"

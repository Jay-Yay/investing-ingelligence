import io
import zipfile

import httpx
import respx

from investor_intel.collectors.dart_client import DartClient
from investor_intel.collectors.dart_corp_code import (
    parse_corp_code_xml,
    resolve_corp_code,
    resolve_dart_company,
    unzip_corp_code_xml,
)
from investor_intel.storage.sqlite_index import connect, init_db, is_dart_corp_code_cache_populated

_API_KEY = "test-api-key"

_SAMPLE_XML = (
    "<?xml version='1.0' encoding='UTF-8'?>\n"
    "<result>\n"
    "  <list>\n"
    "    <corp_code>00126380</corp_code>\n"
    "    <corp_name>삼성전자</corp_name>\n"
    "    <stock_code>005930</stock_code>\n"
    "    <modify_date>20260101</modify_date>\n"
    "  </list>\n"
    "  <list>\n"
    "    <corp_code>00999999</corp_code>\n"
    "    <corp_name>비상장회사</corp_name>\n"
    "    <stock_code></stock_code>\n"
    "    <modify_date>20260102</modify_date>\n"
    "  </list>\n"
    "</result>\n"
)


def _sample_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("CORPCODE.xml", _SAMPLE_XML)
    return buffer.getvalue()


def test_parse_corp_code_xml_returns_all_entries() -> None:
    entries = parse_corp_code_xml(_SAMPLE_XML)

    assert len(entries) == 2
    first = entries[0]
    assert first.corp_code == "00126380"
    assert first.corp_name == "삼성전자"
    assert first.stock_code == "005930"
    assert first.modify_date == "20260101"


def test_parse_corp_code_xml_normalizes_blank_stock_code_to_none() -> None:
    entries = parse_corp_code_xml(_SAMPLE_XML)
    second = entries[1]
    assert second.corp_name == "비상장회사"
    assert second.stock_code is None


def test_unzip_corp_code_xml_extracts_member_text() -> None:
    xml_text = unzip_corp_code_xml(_sample_zip_bytes())
    assert "삼성전자" in xml_text
    assert "005930" in xml_text


@respx.mock
def test_get_bytes_returns_raw_content() -> None:
    zip_bytes = _sample_zip_bytes()
    respx.get(f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={_API_KEY}").mock(
        return_value=httpx.Response(200, content=zip_bytes)
    )
    client = DartClient(api_key=_API_KEY)

    result = client.get_bytes(
        f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={_API_KEY}"
    )
    client.close()

    assert result == zip_bytes


_CORP_CODE_URL = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={_API_KEY}"


@respx.mock
def test_resolve_corp_code_populates_cold_cache_then_resolves(tmp_path) -> None:
    route = respx.get(_CORP_CODE_URL).mock(
        return_value=httpx.Response(200, content=_sample_zip_bytes())
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = DartClient(api_key=_API_KEY)

    corp_code = resolve_corp_code(conn, client, _API_KEY, ticker="005930", name="삼성전자")
    client.close()

    assert corp_code == "00126380"
    assert route.call_count == 1
    assert is_dart_corp_code_cache_populated(conn) is True


@respx.mock
def test_resolve_corp_code_uses_warm_cache_without_network_calls(tmp_path) -> None:
    route = respx.get(_CORP_CODE_URL).mock(
        return_value=httpx.Response(200, content=_sample_zip_bytes())
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = DartClient(api_key=_API_KEY)

    resolve_corp_code(conn, client, _API_KEY, ticker="005930", name="삼성전자")
    assert route.call_count == 1

    second = resolve_corp_code(conn, client, _API_KEY, ticker="005930", name="삼성전자")
    client.close()

    assert second == "00126380"
    assert route.call_count == 1


@respx.mock
def test_resolve_corp_code_returns_none_when_unresolvable(tmp_path) -> None:
    respx.get(_CORP_CODE_URL).mock(
        return_value=httpx.Response(200, content=_sample_zip_bytes())
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = DartClient(api_key=_API_KEY)

    corp_code = resolve_corp_code(conn, client, _API_KEY, ticker="999999", name="존재하지않음")
    client.close()

    assert corp_code is None


@respx.mock
def test_resolve_dart_company_returns_code_and_name_on_cold_cache(tmp_path) -> None:
    respx.get(_CORP_CODE_URL).mock(
        return_value=httpx.Response(200, content=_sample_zip_bytes())
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = DartClient(api_key=_API_KEY)

    result = resolve_dart_company(conn, client, _API_KEY, stock_code="005930")
    client.close()

    assert result == ("00126380", "삼성전자")


@respx.mock
def test_resolve_dart_company_returns_none_when_unresolvable(tmp_path) -> None:
    respx.get(_CORP_CODE_URL).mock(
        return_value=httpx.Response(200, content=_sample_zip_bytes())
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = DartClient(api_key=_API_KEY)

    result = resolve_dart_company(conn, client, _API_KEY, stock_code="000000")
    client.close()

    assert result is None

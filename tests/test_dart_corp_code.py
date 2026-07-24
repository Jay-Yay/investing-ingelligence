import io
import zipfile

import httpx
import respx

from investor_intel.collectors.dart_client import DartClient
from investor_intel.collectors.dart_corp_code import (
    parse_corp_code_xml,
    unzip_corp_code_xml,
)

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

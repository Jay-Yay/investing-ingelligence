import zipfile
from io import BytesIO

import httpx
import respx

from investor_intel.collectors.dart_client import DartClient
from investor_intel.collectors.dart_document_fetch import fetch_full_text

_API_KEY = "test-key"
_URL = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={_API_KEY}&rcept_no=20250814003049"


def _zip_bytes(xml_text: str, member_name: str = "20250814003049.xml") -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member_name, xml_text)
    return buffer.getvalue()


@respx.mock
def test_fetch_full_text_extracts_and_strips_xml() -> None:
    xml = "<DOCUMENT><TITLE>테스트 보고서</TITLE><BODY><P>본문 내용입니다</P></BODY></DOCUMENT>"
    respx.get(_URL).mock(return_value=httpx.Response(200, content=_zip_bytes(xml)))
    client = DartClient(api_key=_API_KEY)

    result = fetch_full_text(client, _API_KEY, "20250814003049")
    client.close()

    assert result is not None
    assert "테스트 보고서" in result
    assert "본문 내용입니다" in result
    assert "<" not in result


@respx.mock
def test_fetch_full_text_returns_none_on_non_zip_response() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, content=b"not a zip file"))
    client = DartClient(api_key=_API_KEY)

    result = fetch_full_text(client, _API_KEY, "20250814003049")
    client.close()

    assert result is None


@respx.mock
def test_fetch_full_text_returns_none_on_http_error() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(500))
    client = DartClient(api_key=_API_KEY)

    result = fetch_full_text(client, _API_KEY, "20250814003049")
    client.close()

    assert result is None


@respx.mock
def test_fetch_full_text_returns_none_when_zip_has_no_xml_member() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "no xml here")
    respx.get(_URL).mock(return_value=httpx.Response(200, content=buffer.getvalue()))
    client = DartClient(api_key=_API_KEY)

    result = fetch_full_text(client, _API_KEY, "20250814003049")
    client.close()

    assert result is None

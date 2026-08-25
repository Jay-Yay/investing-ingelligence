import zipfile
from io import BytesIO

import httpx
import respx

from investor_intel.collectors.dart_client import DartClient
from investor_intel.collectors.dart_document_fetch import decode_document_xml, fetch_full_text

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


def _zip_raw_bytes(payload: bytes, member_name: str = "20250814003049.xml") -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member_name, payload)
    return buffer.getvalue()


@respx.mock
def test_fetch_full_text_decodes_cp949_original() -> None:
    """DART 원문 상당수는 EUC-KR/CP949다. UTF-8로 강제 디코딩하면 한글이 통째로 깨진다."""
    xml = "<DOCUMENT><TITLE>분기보고서</TITLE><BODY><P>주식회사 에이피알</P></BODY></DOCUMENT>"
    respx.get(_URL).mock(
        return_value=httpx.Response(200, content=_zip_raw_bytes(xml.encode("cp949")))
    )
    client = DartClient(api_key=_API_KEY)

    result = fetch_full_text(client, _API_KEY, "20250814003049")
    client.close()

    assert result is not None
    assert "분기보고서" in result
    assert "주식회사 에이피알" in result
    assert "�" not in result


@respx.mock
def test_fetch_full_text_expands_dart_cr_entity() -> None:
    """`&cr;`은 HTML 표준 엔티티가 아니라서 html.unescape가 손대지 않는다."""
    xml = "<DOCUMENT><P>첫 줄&cr;&cr;둘째 줄</P></DOCUMENT>"
    respx.get(_URL).mock(return_value=httpx.Response(200, content=_zip_bytes(xml)))
    client = DartClient(api_key=_API_KEY)

    result = fetch_full_text(client, _API_KEY, "20250814003049")
    client.close()

    assert result is not None
    assert "&cr;" not in result
    assert "첫 줄" in result
    assert "둘째 줄" in result


def test_decode_document_xml_prefers_declared_encoding() -> None:
    raw = '<?xml version="1.0" encoding="euc-kr"?><P>사업보고서</P>'.encode("euc-kr")
    assert "사업보고서" in decode_document_xml(raw)


def test_decode_document_xml_keeps_utf8_when_both_would_decode() -> None:
    """CP949는 UTF-8 한글 바이트열도 (뜻이 깨진 채) 디코딩하므로 UTF-8을 먼저 시도해야 한다."""
    raw = "<P>주식회사</P>".encode()
    assert decode_document_xml(raw) == "<P>주식회사</P>"


def test_decode_document_xml_falls_back_to_replacement_for_unreadable_bytes() -> None:
    """어느 후보로도 안 읽히는 원문은 버리지 않고 넘긴다 - 품질 판정은 하류가 한다."""
    decoded = decode_document_xml(b"\xff\xfe\x00abc\x81")
    assert isinstance(decoded, str)

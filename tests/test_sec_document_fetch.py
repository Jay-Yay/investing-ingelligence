import httpx
import respx

from investor_intel.collectors.sec_client import SECClient
from investor_intel.collectors.sec_document_fetch import fetch_full_text, find_transcript_exhibit

_CIK = "0001664703"
_ACCESSION = "0001628280-25-008747"
_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data/1664703/000162828025008747"


def _client() -> SECClient:
    return SECClient(user_agent="Investor Intel test test@example.com")


@respx.mock
def test_fetch_full_text_extracts_and_strips_html() -> None:
    respx.get(f"{_ARCHIVE_BASE}/be-20241231.htm").mock(
        return_value=httpx.Response(200, text="<html><body><p>테스트 10-K 본문</p></body></html>")
    )
    client = _client()

    result = fetch_full_text(client, _CIK, _ACCESSION, "be-20241231.htm")
    client.close()

    assert result is not None
    assert "테스트 10-K 본문" in result
    assert "<" not in result


@respx.mock
def test_fetch_full_text_returns_none_on_http_error() -> None:
    respx.get(f"{_ARCHIVE_BASE}/be-20241231.htm").mock(return_value=httpx.Response(404))
    client = _client()

    result = fetch_full_text(client, _CIK, _ACCESSION, "be-20241231.htm")
    client.close()

    assert result is None


@respx.mock
def test_find_transcript_exhibit_returns_text_when_operator_and_qa_present() -> None:
    respx.get(f"{_ARCHIVE_BASE}/index.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "directory": {
                    "item": [
                        {"name": "be-20250801.htm", "type": "text.gif"},
                        {"name": "ex991pressrelease.htm", "type": "text.gif"},
                        {"name": "ex992transcript.htm", "type": "text.gif"},
                    ]
                }
            },
        )
    )
    respx.get(f"{_ARCHIVE_BASE}/ex991pressrelease.htm").mock(
        return_value=httpx.Response(200, text="<html><body>보도자료 요약 내용</body></html>")
    )
    respx.get(f"{_ARCHIVE_BASE}/ex992transcript.htm").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<html><body>Operator: Good morning, welcome to the call. "
                "We will now begin the question-and-answer session.</body></html>"
            ),
        )
    )
    client = _client()

    result = find_transcript_exhibit(client, _CIK, _ACCESSION)
    client.close()

    assert result is not None
    assert "question-and-answer" in result.lower()


@respx.mock
def test_find_transcript_exhibit_returns_none_when_no_exhibit_matches_cues() -> None:
    respx.get(f"{_ARCHIVE_BASE}/index.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "directory": {
                    "item": [
                        {"name": "be-20250801.htm", "type": "text.gif"},
                        {"name": "ex991pressrelease.htm", "type": "text.gif"},
                    ]
                }
            },
        )
    )
    respx.get(f"{_ARCHIVE_BASE}/ex991pressrelease.htm").mock(
        return_value=httpx.Response(200, text="<html><body>보도자료 요약 내용</body></html>")
    )
    client = _client()

    result = find_transcript_exhibit(client, _CIK, _ACCESSION)
    client.close()

    assert result is None


@respx.mock
def test_find_transcript_exhibit_returns_none_when_index_fetch_fails() -> None:
    respx.get(f"{_ARCHIVE_BASE}/index.json").mock(return_value=httpx.Response(500))
    client = _client()

    result = find_transcript_exhibit(client, _CIK, _ACCESSION)
    client.close()

    assert result is None

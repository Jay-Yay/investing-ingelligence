import httpx
import respx

from investor_intel.collectors.sec_client import SECClient
from investor_intel.collectors.sec_document_fetch import fetch_full_text, find_earnings_exhibit

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
def test_fetch_full_text_strips_inline_xbrl_hidden_header() -> None:
    """Inline XBRL 문서의 <ix:header>는 화면에 안 보이는 태깅 전용 데이터 블록이다 - 태그만
    벗기면 "amzn-20260630 false 2026 Q2 ..." 류 컨텍스트/유닛 나열이 본문보다 먼저 텍스트로
    새어나와 실질 내용 앞에 쓸모없는 분량만 채운다(AMZN 10-Q 실사례로 발견, 168KB 규모). 이
    헤더 블록은 통째로 제거되고 그 뒤에 오는 실제 본문만 남아야 한다.
    """
    html = (
        "<html><body>"
        "<ix:header>"
        "<ix:hidden>amzn-20260630 false 2026 Q2 http://fasb.org/us-gaap/2026#SomeTag "
        "P2Y 50 339 xbrli:shares iso4217:USD</ix:hidden>"
        "</ix:header>"
        "<p>Table of Contents UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>"
        "</body></html>"
    )
    respx.get(f"{_ARCHIVE_BASE}/amzn-20260630.htm").mock(return_value=httpx.Response(200, text=html))
    client = _client()

    result = fetch_full_text(client, _CIK, _ACCESSION, "amzn-20260630.htm")
    client.close()

    assert result is not None
    assert "fasb.org" not in result
    assert "xbrli:shares" not in result
    assert "UNITED STATES SECURITIES AND EXCHANGE COMMISSION" in result


@respx.mock
def test_find_earnings_exhibit_returns_transcript_when_operator_and_qa_present() -> None:
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

    result = find_earnings_exhibit(client, _CIK, _ACCESSION, filing_items=["2.02", "9.01"])
    client.close()

    assert result is not None
    assert result.is_transcript is True
    assert "question-and-answer" in result.text.lower()


@respx.mock
def test_find_earnings_exhibit_falls_back_to_press_release_when_item_2_02_present() -> None:
    """진짜 녹취록(Operator/Q&A) exhibit이 없어도, 8-K 항목 코드에 2.02(실적/재무상태 결과)가
    있으면 실적 보도자료 exhibit(관례상 99.1)을 대신 캡처해야 한다 - AMZN 8-K 실사례처럼 보도
    자료만 첨부된 경우가 전체의 70~80%를 차지하므로 이 경로가 없으면 대부분의 실적 8-K가
    빈 metadata_only로 남는다.
    """
    respx.get(f"{_ARCHIVE_BASE}/index.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "directory": {
                    "item": [
                        {"name": "be-20250801.htm", "type": "text.gif"},
                        {"name": "ex991pressrelease.htm", "type": "text.gif"},
                        {"name": "ex992nongaap.htm", "type": "text.gif"},
                    ]
                }
            },
        )
    )
    respx.get(f"{_ARCHIVE_BASE}/ex991pressrelease.htm").mock(
        return_value=httpx.Response(
            200, text="<html><body>2분기 매출 1,670억 달러, 순이익 130억 달러 발표</body></html>"
        )
    )
    respx.get(f"{_ARCHIVE_BASE}/ex992nongaap.htm").mock(
        return_value=httpx.Response(200, text="<html><body>Non-GAAP 측정치 설명</body></html>")
    )
    client = _client()

    result = find_earnings_exhibit(client, _CIK, _ACCESSION, filing_items=["2.02", "9.01"])
    client.close()

    assert result is not None
    assert result.is_transcript is False
    assert "매출" in result.text
    # 알파벳순 첫 후보(ex991)를 우선 채택 - SEC 관례상 99.1이 본 보도자료다.
    assert "Non-GAAP" not in result.text


@respx.mock
def test_find_earnings_exhibit_returns_none_when_no_results_item_and_no_transcript_cues() -> None:
    """실적과 무관한 8-K(예: 임원 변경, 인수합병 발표)는 항목 2.02가 없다 - 이런 경우 exhibit이
    있어도 실적 보도자료로 오인해 캡처하면 안 된다.
    """
    respx.get(f"{_ARCHIVE_BASE}/index.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "directory": {
                    "item": [
                        {"name": "be-20250801.htm", "type": "text.gif"},
                        {"name": "ex991announcement.htm", "type": "text.gif"},
                    ]
                }
            },
        )
    )
    respx.get(f"{_ARCHIVE_BASE}/ex991announcement.htm").mock(
        return_value=httpx.Response(200, text="<html><body>임원 선임 발표</body></html>")
    )
    client = _client()

    result = find_earnings_exhibit(client, _CIK, _ACCESSION, filing_items=["5.02"])
    client.close()

    assert result is None


@respx.mock
def test_find_earnings_exhibit_returns_none_when_index_fetch_fails() -> None:
    respx.get(f"{_ARCHIVE_BASE}/index.json").mock(return_value=httpx.Response(500))
    client = _client()

    result = find_earnings_exhibit(client, _CIK, _ACCESSION, filing_items=["2.02"])
    client.close()

    assert result is None

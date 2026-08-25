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
    respx.get(f"{_ARCHIVE_BASE}/amzn-20260630.htm").mock(
        return_value=httpx.Response(200, text=html)
    )
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

    result = find_earnings_exhibit(
        client,
        _CIK,
        _ACCESSION,
        filing_items=["2.02", "9.01"],
        primary_document="be-20250801.htm",
    )
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

    result = find_earnings_exhibit(
        client,
        _CIK,
        _ACCESSION,
        filing_items=["2.02", "9.01"],
        primary_document="be-20250801.htm",
    )
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

    result = find_earnings_exhibit(
        client, _CIK, _ACCESSION, filing_items=["5.02"], primary_document="be-20250801.htm"
    )
    client.close()

    assert result is None


@respx.mock
def test_find_earnings_exhibit_captures_press_release_named_without_ex99_convention() -> None:
    """실사례(CRWV 2026-08-11 8-K): 실적 보도자료 exhibit이 "coreweave2q26earningspress.htm"처럼
    회사가 임의로 지은 파일명을 쓰면 "ex99" 관례 기반 정규식으로는 후보에서 걸러져 금액
    누락(metadata_only)으로 남았다. 파일명 관례가 아니라 primaryDocument/XBRL 뷰어 조각만
    제외하는 방식으로 찾아야 한다.
    """
    respx.get(f"{_ARCHIVE_BASE}/index.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "directory": {
                    "item": [
                        {"name": "crwv-20260811.htm", "type": "text.gif"},
                        {"name": "coreweave2q26earningspress.htm", "type": "text.gif"},
                        {"name": "R1.htm", "type": "text.gif"},
                    ]
                }
            },
        )
    )
    respx.get(f"{_ARCHIVE_BASE}/coreweave2q26earningspress.htm").mock(
        return_value=httpx.Response(200, text="<html><body>2분기 매출 12억 달러 발표</body></html>")
    )
    client = _client()

    result = find_earnings_exhibit(
        client,
        _CIK,
        _ACCESSION,
        filing_items=["2.02", "9.01"],
        primary_document="crwv-20260811.htm",
    )
    client.close()

    assert result is not None
    assert result.is_transcript is False
    assert "매출" in result.text


@respx.mock
def test_find_earnings_exhibit_excludes_primary_document_and_xbrl_viewer_fragments() -> None:
    """primaryDocument 자체와 iXBRL 뷰어가 생성하는 "R숫자.htm" 조각은 실적 exhibit 후보가
    아니다 - 후보에 섞이면 R1.htm(커버페이지 XBRL 조각)이 실적 보도자료로 오인될 수 있다.
    """
    respx.get(f"{_ARCHIVE_BASE}/index.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "directory": {
                    "item": [
                        {"name": "be-20250801.htm", "type": "text.gif"},
                        {"name": "R1.htm", "type": "text.gif"},
                    ]
                }
            },
        )
    )
    client = _client()

    result = find_earnings_exhibit(
        client,
        _CIK,
        _ACCESSION,
        filing_items=["2.02", "9.01"],
        primary_document="be-20250801.htm",
    )
    client.close()

    assert result is None


@respx.mock
def test_find_earnings_exhibit_force_flag_captures_6k_earnings_exhibit_without_item_codes() -> None:
    """실사례(NBIS 6-K): FPI의 6-K는 8-K 항목 코드가 없어 filing_items가 비어 있다. 호출부가
    period_of_report 존재 등으로 "이 6-K는 실적 관련"이라 판단해 force_results_exhibit_search=True로
    넘기면, 항목 코드 없이도 보도자료 exhibit을 캡처해야 한다.
    """
    respx.get(f"{_ARCHIVE_BASE}/index.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "directory": {
                    "item": [
                        {"name": "tm2622968d1_6k.htm", "type": "text.gif"},
                        {"name": "tm2622968d1_ex99-1.htm", "type": "text.gif"},
                        {"name": "tm2622968d1_ex99-2.htm", "type": "text.gif"},
                    ]
                }
            },
        )
    )
    respx.get(f"{_ARCHIVE_BASE}/tm2622968d1_ex99-1.htm").mock(
        return_value=httpx.Response(200, text="<html><body>2분기 매출 5억 달러 발표</body></html>")
    )
    respx.get(f"{_ARCHIVE_BASE}/tm2622968d1_ex99-2.htm").mock(
        return_value=httpx.Response(200, text="<html><body>투자자 프레젠테이션</body></html>")
    )
    client = _client()

    result = find_earnings_exhibit(
        client,
        _CIK,
        _ACCESSION,
        filing_items=[],
        primary_document="tm2622968d1_6k.htm",
        force_results_exhibit_search=True,
    )
    client.close()

    assert result is not None
    assert result.is_transcript is False
    assert "매출" in result.text


@respx.mock
def test_find_earnings_exhibit_returns_none_when_index_fetch_fails() -> None:
    respx.get(f"{_ARCHIVE_BASE}/index.json").mock(return_value=httpx.Response(500))
    client = _client()

    result = find_earnings_exhibit(
        client, _CIK, _ACCESSION, filing_items=["2.02"], primary_document="be-20250801.htm"
    )
    client.close()

    assert result is None

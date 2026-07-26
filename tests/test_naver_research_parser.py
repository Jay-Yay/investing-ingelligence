import json

from investor_intel.collectors.naver_research_parser import (
    parse_naver_research_detail,
    parse_naver_research_list,
    parse_weekly_hot_list,
)

_LIST_JSON = json.dumps(
    [
        {
            "researchCategory": "종목분석",
            "category": "종목분석",
            "itemCode": "017670",
            "itemName": "SK텔레콤",
            "researchId": 94484,
            "title": "AIDC 사업개발 전문회사 SK하이퍼 설립 관련 Comment",
            "brokerName": "신한투자증권",
            "writeDate": "2026-07-24",
            "readCount": "6257",
            "endUrl": "https://m.stock.naver.com/research/company/94484",
        },
        {
            "researchCategory": "종목분석",
            "itemCode": "251970",
            "itemName": "펌텍코리아",
            "researchId": 94483,
            "title": "정상화, 개선 그리고 추가 증설",
            "brokerName": "한화투자증권",
            "writeDate": "2026-07-24",
        },
        {"researchCategory": "종목분석", "title": "researchId 없는 항목은 건너뜀"},
    ]
)

_DETAIL_JSON = json.dumps(
    {
        "researchContent": {
            "itemCode": "017670",
            "itemName": "SK텔레콤",
            "researchId": 94484,
            "title": "AIDC 사업개발 전문회사 SK하이퍼 설립 관련 Comment",
            "brokerName": "신한투자증권",
            "writeDate": "2026-07-24",
            "attachUrl": "https://stock.pstatic.net/stock-research/company/21/report.pdf",
            "content": "<p>본문 문단 1<br>줄바꿈 포함</p>",
            "opinion": "매수",
            "goalPrice": "100000",
            "prevGoalPrice": "104700",
            "priceAtWriteDate": "104700",
        },
        "researchSummaries": [],
    }
)


def test_parse_naver_research_list_extracts_stubs_and_skips_missing_research_id() -> None:
    stubs = parse_naver_research_list(_LIST_JSON)

    assert len(stubs) == 2
    first = stubs[0]
    assert first.research_id == 94484
    assert first.item_code == "017670"
    assert first.item_name == "SK텔레콤"
    assert first.title == "AIDC 사업개발 전문회사 SK하이퍼 설립 관련 Comment"
    assert first.broker_name == "신한투자증권"
    assert first.write_date.isoformat() == "2026-07-24"


def test_parse_naver_research_detail_extracts_structured_fields() -> None:
    detail = parse_naver_research_detail(_DETAIL_JSON)

    assert detail.opinion == "매수"
    assert detail.goal_price == 100000.0
    assert detail.prev_goal_price == 104700.0
    assert detail.attach_url == "https://stock.pstatic.net/stock-research/company/21/report.pdf"
    assert "본문 문단 1" in detail.content_text
    assert "<p>" not in detail.content_text


def test_parse_naver_research_detail_handles_missing_goal_price() -> None:
    data = json.dumps({"researchContent": {"content": None, "opinion": None}})
    detail = parse_naver_research_detail(data)

    assert detail.goal_price is None
    assert detail.prev_goal_price is None
    assert detail.content_text is None
    assert detail.opinion is None


def test_parse_naver_research_detail_handles_unwrapped_payload() -> None:
    # defensive: fall back to the top-level object if a future response isn't wrapped in
    # "researchContent"
    data = json.dumps({"opinion": "매수", "goalPrice": "50000"})
    detail = parse_naver_research_detail(data)

    assert detail.opinion == "매수"
    assert detail.goal_price == 50000.0


def test_parse_naver_research_detail_extracts_item_name() -> None:
    data = json.dumps({"researchContent": {"itemName": "SK텔레콤"}})
    detail = parse_naver_research_detail(data)
    assert detail.item_name == "SK텔레콤"


_WEEKLY_HOT_JSON = json.dumps(
    {
        "startDate": "2026-07-19",
        "researchList": [
            {
                "ranking": "1",
                "type": "company",
                "nid": "94282",
                "title": "2Q26 프리뷰: 우려를 넘어 로봇 모멘텀 주목",
                "brokerName": "미래에셋증권",
                "writeDate": "2026-07-21",
                "readCount": "11774",
                "itemCode": "005380",
                "analystName": None,
            },
            {
                "ranking": "2",
                "nid": "94277",
                "title": "수요와 공급 모두 여전히 우호적인 상황",
                "brokerName": "하나증권",
                "writeDate": "2026-07-20",
                "itemCode": "009150",
            },
            {"ranking": "3", "title": "nid 없는 항목은 건너뜀"},
        ],
    }
)


def test_parse_weekly_hot_list_extracts_ranked_stubs() -> None:
    stubs = parse_weekly_hot_list(_WEEKLY_HOT_JSON)

    assert len(stubs) == 2
    first = stubs[0]
    assert first.research_id == 94282
    assert first.rank == 1
    assert first.item_code == "005380"
    assert first.item_name == ""
    assert first.title == "2Q26 프리뷰: 우려를 넘어 로봇 모멘텀 주목"
    assert first.broker_name == "미래에셋증권"
    assert first.write_date.isoformat() == "2026-07-21"

    second = stubs[1]
    assert second.research_id == 94277
    assert second.rank == 2


def test_parse_weekly_hot_list_handles_empty_research_list() -> None:
    assert parse_weekly_hot_list(json.dumps({"startDate": "2026-07-26", "researchList": []})) == []

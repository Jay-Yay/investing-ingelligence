from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from investor_intel.indexing.router import RetrievalPolicy, Router
from investor_intel.indexing.structured import _parse_holdings_table
from investor_intel.indexing.tools import HoldingsTool


def test_needs_retrieval_skips_greetings_but_keeps_questions() -> None:
    # 4주차 §9: 모든 질문이 외부 검색을 필요로 하지는 않는다
    assert Router.needs_retrieval("삼성전자 2010년 분기보고서 접수번호")
    assert not Router.needs_retrieval("안녕하세요")
    assert not Router.needs_retrieval("hi there")
    # 한글에는 \b 단어 경계가 안 걸린다. '안녕하세요'가 걸러지는지가 그 회귀 테스트다.
    assert not Router.needs_retrieval("반갑습니다")


@pytest.mark.parametrize(("query", "expected"), [
    ("베일리기포드 2025년 4분기 13F 편입 종목 개수", "query_holdings"),
    ("포트폴리오 상위 5종목 쏠림 정도", "query_holdings"),
    ("삼성전자 2010년 1분기 분기보고서 접수번호", "lookup_filing"),
    ("사업보고서 언제 제출됐나", "lookup_filing"),
    ("하워드 막스가 신용 사고를 어떤 전조로 봤나", "search_documents"),
])
def test_router_picks_the_index_type_the_question_needs(query: str, expected: str) -> None:
    assert Router.route(query) == expected


def test_holdings_table_is_parsed_back_into_rows() -> None:
    body = (
        "총 보고 가치: 1,401,301천 달러 / 보유 종목 수: 46 / 상위 5종목 집중도: 36.14%\n\n"
        "| 종목 | CUSIP | 수량 | 보고가치($천) | 비중 | 변화 | Put/Call |\n"
        "| --- | --- | ---: | ---: | ---: | --- | --- |\n"
        "| Alcoa Inc. | 013817101 | 5,744,000 | 85,528 | 6.10% | increased | - |\n"
        "| Google Inc | 38259P508 | 200,000 | 116,900 | 8.34% | new | - |\n")
    rows = _parse_holdings_table(body)
    assert len(rows) == 2
    assert rows[0]["security"] == "Alcoa Inc." and rows[0]["weight_pct"] == 6.10
    assert rows[1]["shares"] == 200000


def test_position_count_comes_from_the_header_not_the_row_count(tmp_path: Path) -> None:
    """수집기가 13F 표를 잘라 저장하기 때문에 행을 세면 실제 보유 종목 수와 다르다.

    실측: 스냅샷 198건 중 93건이 잘렸고, 보고된 48,065종목 중 58.7%가 표에 없다.
    그래서 개수 질문은 표가 아니라 보고서 머리글 값으로 답해야 한다.
    """
    db = tmp_path / "s.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE snapshots (concept_id TEXT PRIMARY KEY, investor_key TEXT,"
        " investor TEXT, as_of TEXT, published TEXT, total_value_k INTEGER,"
        " reported_count INTEGER, top5_pct REAL, captured_rows INTEGER, truncated INTEGER);"
        "CREATE TABLE holdings (concept_id TEXT, investor_key TEXT, investor TEXT,"
        " as_of TEXT, published TEXT, security TEXT, cusip TEXT, shares INTEGER,"
        " value_k INTEGER, weight_pct REAL, change TEXT);")
    conn.execute("INSERT INTO snapshots VALUES ('c1','inv-bg','BAILLIE GIFFORD & CO',"
                 "'2025-Q4','2026-01-23',900000,902,15.89,287,1)")
    conn.execute("INSERT INTO holdings VALUES ('c1','inv-bg','BAILLIE GIFFORD & CO',"
                 "'2025-Q4','2026-01-23','NVIDIA','x',1,1,4.2,'held')")
    conn.commit(); conn.close()

    tool = HoldingsTool(db)
    res = tool.run("베일리기포드 2025년 4분기 편입 종목 개수")
    assert res.ok and "902" in res.answer          # 287(표 행 수)이 아니다
    assert res.note and "287" in res.note          # 잘렸다는 사실은 반드시 함께 알린다


def test_retrieval_policy_makes_the_operating_limits_explicit() -> None:
    # 4주차 §12가 요구한 통제 항목들이 흩어져 있지 않고 한곳에 있는지
    p = RetrievalPolicy()
    assert p.max_retries >= 1
    assert p.forbid_repeat_query is True
    assert p.min_evidence >= 1
    assert 0 < p.escalate_to_human_below < 1
    assert p.max_latency_ms > 0

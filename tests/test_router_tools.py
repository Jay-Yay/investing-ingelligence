from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from investor_intel.indexing.router import RetrievalPolicy, Router
from investor_intel.indexing.structured import (
    _SCHEMA,
    _parse_holdings_table,
    parse_snapshot_header,
)
from investor_intel.indexing.tools import HoldingsTool


def _snapshot_db(
    tmp_path: Path,
    reported_count: int,
    captured_rows: int,
    truncated: int,
    legacy_units: int = 0,
) -> Path:
    """실제 스키마(`structured._SCHEMA`)로 스냅샷 1건을 만든다.

    예전에는 이 테스트가 스키마를 손으로 다시 적었는데, 그러면 본 스키마가 바뀔 때
    테스트만 옛 컬럼을 보고 통과하거나(거짓 안심) 엉뚱한 곳에서 깨진다.
    """
    db = tmp_path / "s.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO snapshots (concept_id,investor_key,investor,as_of,published,"
        "total_value_usd,reported_count,top5_pct,captured_rows,truncated,legacy_units)"
        " VALUES ('c1','inv-bg','BAILLIE GIFFORD & CO','2025-Q4','2026-01-23',"
        f"900000000,{reported_count},15.89,{captured_rows},{truncated},{legacy_units})")
    conn.execute(
        "INSERT INTO holdings (concept_id,investor_key,investor,as_of,published,security,"
        "cusip,shares,value_usd,weight_pct,change,row_count)"
        " VALUES ('c1','inv-bg','BAILLIE GIFFORD & CO','2025-Q4','2026-01-23','NVIDIA',"
        "'67066G104',1,1,4.2,'held',1)")
    conn.commit()
    conn.close()
    return db


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
    db = _snapshot_db(tmp_path, reported_count=902, captured_rows=287, truncated=1)

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


def test_legacy_format_snapshot_answers_but_warns(tmp_path: Path) -> None:
    """옛 수집 형식으로 저장된 스냅샷은 금액·비중이 틀려 있다.

    보정할 방법이 없으므로(원문 재수집이 필요하다) 답은 내되 한계를 반드시 함께 알린다.
    """
    db = _snapshot_db(tmp_path, reported_count=46, captured_rows=46, truncated=0,
                      legacy_units=1)
    res = HoldingsTool(db).run("베일리기포드 2025년 4분기 총 보고 가치")
    assert res.ok
    assert res.note is not None and "신뢰할 수 없" in res.note


def test_current_format_snapshot_has_no_legacy_warning(tmp_path: Path) -> None:
    db = _snapshot_db(tmp_path, reported_count=46, captured_rows=46, truncated=0)
    res = HoldingsTool(db).run("베일리기포드 2025년 4분기 총 보고 가치")
    assert res.ok and res.note is None


def test_snapshot_header_parses_current_format() -> None:
    header = parse_snapshot_header(
        "총 보고 가치: 266,378,900,503 달러 / 보유 포지션 수: 37 (원문 121행)"
        " / 상위 5종목 집중도: 46.49%")
    assert header is not None
    assert header.total_value_usd == 266_378_900_503
    assert header.reported_count == 37
    assert header.top5_pct == 46.49
    assert header.legacy_units is False


def test_snapshot_header_normalizes_legacy_thousands_and_flags_it() -> None:
    header = parse_snapshot_header(
        "총 보고 가치: 1,401,301천 달러 / 보유 종목 수: 46 / 상위 5종목 집중도: 36.14%")
    assert header is not None
    assert header.total_value_usd == 1_401_301_000
    assert header.legacy_units is True


def test_holdings_table_row_count_column_is_read_when_present() -> None:
    """현행 표에는 '원문행수' 열이 있다. 합산된 포지션임을 표에서도 알 수 있어야 한다."""
    body = (
        "| 종목 | CUSIP | 수량 | 보고가치($) | 비중 | 변화 | Put/Call | 원문행수 |\n"
        "| --- | --- | ---: | ---: | ---: | --- | --- | ---: |\n"
        "| APPLE INC | 037833100 | 300,000,000 | 69,900,000,000 | 26.24% | held | - | 12 |\n")
    (row,) = _parse_holdings_table(body)
    assert row["row_count"] == 12
    assert row["value_usd"] == 69_900_000_000


# --- Hybrid Search 연결 ------------------------------------------------------------------


def _companies_bundle(tmp_path: Path, companies: dict) -> Path:
    bundle = tmp_path / "bundle" / "companies"
    bundle.mkdir(parents=True, exist_ok=True)
    for key, title in companies.items():
        (bundle / f"{key}.md").write_text(
            f"---\ntype: Company\ntitle: {title}\n---\n", encoding="utf-8")
    return tmp_path / "bundle"


def _seed_chunk_db(chunk_db: Path, records: list) -> None:
    from investor_intel.indexing.bm25_index import Bm25Index
    index = Bm25Index(chunk_db, korean_ngram=True, korean_keep_word=True)
    index.build(records)
    index.close()


def _record(doc_id: str, body: str, *, source_name: str = "ch", entity_key: str = "",
           okf_status: str = "stable") -> tuple:
    return (
        {"chunk_uid": f"{doc_id}#0", "doc_id": doc_id, "ord": 0, "doc_path": "p",
         "source_type": "telegram", "source_name": source_name, "published_at": "2026-07-08",
         "title": body[:10], "filing_type": None, "capture_mode": "full", "heading_path": "",
         "kind": "prose", "n_chars": len(body), "raw_text": body,
         "okf_status": okf_status, "entity_key": entity_key},
        body, body[:10], body,
    )


def test_router_search_documents_works_bm25_only_when_no_vector_backend_given(
    tmp_path: Path,
) -> None:
    """Hybrid는 선택 사항이다 - vector_index/encoder를 안 주면 BM25 단독으로 동작해야 한다."""
    bundle = _companies_bundle(tmp_path, {})
    chunk_db = tmp_path / "chunk.sqlite3"
    _seed_chunk_db(chunk_db, [_record("a", "에이피알 실적 발표 좋은 소식")])
    router = Router(bundle, chunk_db, tmp_path / "structured.sqlite3")
    assert not router.docs.retriever.vector_enabled
    result = router.answer("에이피알 실적 어땠나")
    assert result.tool == "search_documents"
    assert result.result.ok


def test_router_search_documents_becomes_hybrid_when_vector_backend_given(
    tmp_path: Path,
) -> None:
    from investor_intel.indexing.embedding import HashEncoder
    from investor_intel.indexing.vector_index import VectorIndex

    bundle = _companies_bundle(tmp_path, {})
    chunk_db = tmp_path / "chunk.sqlite3"
    _seed_chunk_db(chunk_db, [_record("a", "에이피알 실적 발표 좋은 소식")])

    vec = VectorIndex(tmp_path / "vec.sqlite3")
    vec.build([{"embed_text": "에이피알 실적 발표 좋은 소식", "chunk_uid": "a#0", "doc_id": "a",
                "ord": 0, "title": "제목", "source_type": "telegram", "n_chars": 10,
                "raw_text": "에이피알 실적 발표 좋은 소식"}], HashEncoder())

    router = Router(bundle, chunk_db, tmp_path / "structured.sqlite3",
                    vector_index=vec, encoder=HashEncoder())
    assert router.docs.retriever.vector_enabled


# --- corrupt 기본 제외가 Router.answer 경로 전체에서 지켜지는지 --------------------------


def test_corrupt_evidence_carries_a_warning_note_through_the_router(tmp_path: Path) -> None:
    """근거가 하나도 없어 corrupt를 최후 수단으로 꺼내면, 그 사실이 note에 반드시 남아야
    한다 - 이게 빠지면 손상된 본문이 경고 없이 근거로 인용된다."""
    bundle = _companies_bundle(tmp_path, {})
    chunk_db = tmp_path / "chunk.sqlite3"
    _seed_chunk_db(chunk_db, [_record("broken", "에이피알 실적 관련 내용", okf_status="corrupt")])
    router = Router(bundle, chunk_db, tmp_path / "structured.sqlite3")
    result = router.answer("에이피알 실적 발표")
    assert result.result.ok
    assert result.result.note is not None and "인코딩이 깨져" in result.result.note


# --- 그래프 탐색 (2-hop) ------------------------------------------------------------------


def test_graph_tool_finds_entities_co_mentioned_by_the_same_channel(tmp_path: Path) -> None:
    from investor_intel.indexing.tools import GraphTool

    bundle = _companies_bundle(tmp_path, {"kr-278470": "에이피알", "kr-090430": "아모레퍼시픽"})
    chunk_db = tmp_path / "chunk.sqlite3"
    _seed_chunk_db(chunk_db, [
        _record("a", "에이피알 실적", source_name="뷰티채널", entity_key="|kr-278470|"),
        _record("b", "아모레퍼시픽 실적", source_name="뷰티채널", entity_key="|kr-090430|"),
        _record("c", "무관한 채널의 무관한 글", source_name="다른채널", entity_key="|kr-090430|"),
    ])
    from investor_intel.indexing.bm25_index import Bm25Index
    from investor_intel.indexing.retrieval import EntityLexicon
    index = Bm25Index(chunk_db, korean_ngram=True, korean_keep_word=True)
    lex = EntityLexicon(bundle)
    tool = GraphTool(index, lex)

    res = tool.run("에이피알을 다룬 채널이 또 무엇을 언급했나")
    assert res.ok
    assert res.evidence[0]["entity_key"] == "kr-090430"
    # '다른채널'은 에이피알을 다루지 않았으므로 hop 1에서 제외되고, 카운트에 안 들어간다.
    assert res.evidence[0]["count"] == 1
    index.close()


def test_graph_tool_reports_no_channel_found(tmp_path: Path) -> None:
    from investor_intel.indexing.tools import GraphTool

    bundle = _companies_bundle(tmp_path, {"kr-278470": "에이피알"})
    chunk_db = tmp_path / "chunk.sqlite3"
    _seed_chunk_db(chunk_db, [_record("a", "무관한 내용")])
    from investor_intel.indexing.bm25_index import Bm25Index
    from investor_intel.indexing.retrieval import EntityLexicon
    index = Bm25Index(chunk_db, korean_ngram=True, korean_keep_word=True)
    tool = GraphTool(index, EntityLexicon(bundle))
    res = tool.run("에이피알을 다룬 채널이 또 무엇을 언급했나")
    assert not res.ok
    index.close()


def test_graph_tool_excludes_corrupt_chunks_from_both_hops(tmp_path: Path) -> None:
    from investor_intel.indexing.tools import GraphTool

    bundle = _companies_bundle(tmp_path, {"kr-278470": "에이피알"})
    chunk_db = tmp_path / "chunk.sqlite3"
    _seed_chunk_db(chunk_db, [
        _record("a", "에이피알 실적", source_name="뷰티채널", entity_key="|kr-278470|",
                okf_status="corrupt"),
    ])
    from investor_intel.indexing.bm25_index import Bm25Index
    from investor_intel.indexing.retrieval import EntityLexicon
    index = Bm25Index(chunk_db, korean_ngram=True, korean_keep_word=True)
    tool = GraphTool(index, EntityLexicon(bundle))
    res = tool.run("에이피알을 다룬 채널이 또 무엇을 언급했나")
    assert not res.ok  # hop 1 자체가 corrupt만 있어 채널을 찾지 못한다
    index.close()


def test_router_routes_relationship_questions_to_the_graph_tool() -> None:
    assert Router.route("에이피알을 다룬 채널이 최근 또 무엇을 언급했나") == "graph_traverse"
    assert Router.route("에이피알과 함께 언급된 종목이 뭐야") == "graph_traverse"

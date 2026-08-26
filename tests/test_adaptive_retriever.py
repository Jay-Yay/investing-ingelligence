from __future__ import annotations

from pathlib import Path

from investor_intel.indexing.bm25_index import Bm25Index
from investor_intel.indexing.retrieval import (
    DEFAULT_EXCLUDE_STATUS,
    AdaptiveRetriever,
    EntityLexicon,
    RetrievalPolicy,
)


def _lexicon(tmp_path: Path, companies: dict[str, str]) -> EntityLexicon:
    bundle = tmp_path / "bundle" / "companies"
    bundle.mkdir(parents=True, exist_ok=True)
    for key, title in companies.items():
        (bundle / f"{key}.md").write_text(
            f"---\ntype: Company\ntitle: {title}\n---\n", encoding="utf-8")
    return EntityLexicon(tmp_path / "bundle")


def _record(doc_id: str, body: str, *, okf_status: str = "stable",
           entity_key: str = "", period_year: str = "", okf_type: str = "MarketCommentary",
           source_name: str = "ch") -> tuple[dict, str, str, str]:
    return (
        {"chunk_uid": f"{doc_id}#0", "doc_id": doc_id, "ord": 0, "doc_path": "p",
         "source_type": "telegram", "source_name": source_name, "published_at": "2026-07-08",
         "title": body[:10], "filing_type": None, "capture_mode": "full", "heading_path": "",
         "kind": "prose", "n_chars": len(body), "raw_text": body,
         "okf_status": okf_status, "okf_type": okf_type, "entity_key": entity_key,
         "period_year": period_year, "pub_year": period_year},
        body, body[:10], body,
    )


def _index(tmp_path: Path, records: list) -> Bm25Index:
    index = Bm25Index(tmp_path / "idx.sqlite3", korean_ngram=True, korean_keep_word=True)
    index.build(records)
    return index


# --- exclude_status 기본 적용 -------------------------------------------------------------


def test_corrupt_documents_are_excluded_by_default(tmp_path: Path) -> None:
    lex = _lexicon(tmp_path, {})
    index = _index(tmp_path, [
        _record("clean", "에이피알 실적 발표 내용", okf_status="stable"),
        _record("broken", "에이피알 실적 발표 내용", okf_status="corrupt"),
    ])
    retriever = AdaptiveRetriever(index, lex)
    result = retriever.search("에이피알 실적", adaptive=False)
    assert {h.doc_id for h in result.hits} == {"clean"}
    index.close()


def test_exclude_status_is_relaxed_only_as_a_last_resort_when_nothing_else_matches(
    tmp_path: Path,
) -> None:
    """정상 문서가 하나라도 있으면 corrupt를 굳이 꺼내지 않는다."""
    lex = _lexicon(tmp_path, {})
    index = _index(tmp_path, [
        _record("clean", "코스맥스 해외 매출 좋다는 소식", okf_status="stable"),
        _record("broken", "에이피알 실적 발표 내용", okf_status="corrupt"),
    ])
    retriever = AdaptiveRetriever(index, lex, grade_threshold=0.9)
    result = retriever.search("에이피알 실적")
    # 근거가 전혀 없을 때만 relax_status_filter가 실행된다 - clean 문서와 무관한 질의라
    # BM25는 아무것도 못 찾고, corrupt만이라도 돌려준다.
    assert any(s.action == "relax_status_filter" for s in result.steps)
    assert {h.doc_id for h in result.hits} == {"broken"}
    index.close()


def test_exclude_status_can_be_turned_off_entirely(tmp_path: Path) -> None:
    lex = _lexicon(tmp_path, {})
    index = _index(tmp_path, [_record("broken", "본문 내용", okf_status="corrupt")])
    retriever = AdaptiveRetriever(index, lex, exclude_status=())
    result = retriever.search("본문", adaptive=False)
    assert {h.doc_id for h in result.hits} == {"broken"}
    index.close()


# --- RetrievalPolicy 강제 ------------------------------------------------------------------


def test_max_retries_bounds_the_number_of_steps(tmp_path: Path) -> None:
    lex = _lexicon(tmp_path, {"kr-278470": "에이피알"})
    index = _index(tmp_path, [])  # 아무것도 없어 완화가 끝없이 시도된다
    retriever = AdaptiveRetriever(
        index, lex, policy=RetrievalPolicy(max_retries=1), grade_threshold=0.9)
    result = retriever.search("에이피알 2026년 실적")
    # escalate는 검색을 수행하지 않는 마무리 기록이라 예산에서 뺀다 - 실제로 검색을
    # 실행한 단계(retrieve/relax_filter/rewrite_query/relax_status_filter)만 센다.
    search_steps = [s for s in result.steps if s.action != "escalate"]
    assert len(search_steps) <= retriever.max_steps
    assert retriever.max_steps == 2
    index.close()


def test_forbid_repeat_query_stops_the_same_search_from_running_twice(tmp_path: Path) -> None:
    """완화할 필터가 이미 다 떨어졌는데 같은 (질의, 필터) 조합을 또 시도하면 안 된다."""
    lex = _lexicon(tmp_path, {})
    index = _index(tmp_path, [_record("a", "완전히 무관한 내용")])
    retriever = AdaptiveRetriever(
        index, lex, policy=RetrievalPolicy(max_retries=5, forbid_repeat_query=True),
        grade_threshold=0.99)
    result = retriever.search("에이피알 실적이 얼마나 늘었나")
    kinds = [s.action for s in result.steps]
    # rewrite 단계가 원 질의와 다른 문자열을 만들지 못하면 반복 없이 끝나야 한다.
    assert kinds.count("rewrite_query") <= 1
    index.close()


def test_escalate_flag_is_set_when_coverage_stays_low(tmp_path: Path) -> None:
    lex = _lexicon(tmp_path, {})
    index = _index(tmp_path, [_record("a", "완전히 무관한 내용")])
    retriever = AdaptiveRetriever(
        index, lex, policy=RetrievalPolicy(escalate_to_human_below=0.99), grade_threshold=0.5)
    result = retriever.search("에이피알 실적 목표주가 상향")
    assert result.escalate is True
    assert any(s.action == "escalate" for s in result.steps)


def test_escalate_flag_is_false_when_coverage_is_high(tmp_path: Path) -> None:
    lex = _lexicon(tmp_path, {})
    index = _index(tmp_path, [_record("a", "에이피알 실적 목표주가 상향 발표")])
    retriever = AdaptiveRetriever(
        index, lex, policy=RetrievalPolicy(escalate_to_human_below=0.05))
    result = retriever.search("에이피알 실적 목표주가")
    assert result.escalate is False
    index.close()


def test_max_latency_ms_stops_the_loop_early(tmp_path: Path) -> None:
    lex = _lexicon(tmp_path, {"kr-278470": "에이피알"})
    index = _index(tmp_path, [])
    retriever = AdaptiveRetriever(
        index, lex, policy=RetrievalPolicy(max_retries=5, max_latency_ms=0),
        grade_threshold=0.9)
    result = retriever.search("에이피알 2026년 실적 발표")
    assert any(s.action == "timeout" for s in result.steps)
    index.close()


def test_default_policy_preserves_the_original_three_step_budget(tmp_path: Path) -> None:
    """policy 도입 전 기본값(max_steps=3)과 동일해야 기존 호출부가 안 깨진다."""
    lex = _lexicon(tmp_path, {})
    index = _index(tmp_path, [])
    retriever = AdaptiveRetriever(index, lex)
    assert retriever.max_steps == 3
    index.close()


# --- Reranker가 실제 실패 사례를 고치는지 (통합) -------------------------------------------


def test_rerank_promotes_the_target_company_over_the_analyst_house_flood(tmp_path: Path) -> None:
    """"교보증권이 제시한 에이피알 목표주가" 실패 사례의 재현.

    교보증권(분석 주체)이 다룬 다른 종목 리포트가 여러 건이라 BM25 원본 순위에서는
    상위를 차지하지만, 실제 대상인 에이피알 문서는 entity_key가 명확하다. 필터가
    relax됐더라도 재랭킹이 대상 종목 문서를 앞으로 당겨야 한다.
    """
    lex = _lexicon(tmp_path, {"kr-278470": "에이피알", "kr-030610": "교보증권"})
    index = _index(tmp_path, [
        _record("other1", "교보증권 리포트 현대위아 실적 리뷰", entity_key="|kr-004920|"),
        _record("other2", "교보증권 리포트 하이브 실적 리뷰", entity_key="|kr-352820|"),
        _record("other3", "교보증권 리포트 LS일렉트릭 실적 리뷰", entity_key="|kr-010120|"),
        _record("target", "교보증권 리서치 에이피알 목표주가 상향", entity_key="|kr-278470|"),
    ])
    retriever = AdaptiveRetriever(index, lex)
    result = retriever.search("교보증권이 제시한 에이피알 목표주가")
    assert result.hits[0].doc_id == "target"
    index.close()

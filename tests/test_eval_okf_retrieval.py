from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from eval_okf_retrieval import native_id_map, resolve_gold, score  # noqa: E402

from investor_intel.indexing.bm25_index import Bm25Index
from investor_intel.indexing.retrieval import AdaptiveRetriever, EntityLexicon


def _record(doc_id: str, body: str, *, native_doc_id: str = "", okf_status: str = "stable",
           source_type: str = "telegram") -> tuple:
    return (
        {"chunk_uid": f"{doc_id}#0", "doc_id": doc_id, "ord": 0, "doc_path": "p",
         "source_type": source_type, "source_name": "s", "published_at": "2026-07-08",
         "title": body[:10], "filing_type": None, "capture_mode": "full", "heading_path": "",
         "kind": "prose", "n_chars": len(body), "raw_text": body,
         "okf_status": okf_status, "native_doc_id": native_doc_id},
        body, body[:10], body,
    )


@pytest.fixture()
def index(tmp_path: Path):
    idx = Bm25Index(tmp_path / "idx.sqlite3", korean_ngram=True, korean_keep_word=True)
    idx.build([
        _record("concept-a", "에이피알 실적 발표 좋은 소식", native_doc_id="native-a"),
        _record("concept-b", "무관한 내용", native_doc_id="native-b"),
        _record("concept-corrupt", "손상된 문서 접수번호 조회", native_doc_id="native-c",
                okf_status="corrupt"),
        # BM25가 "손상된 문서 접수번호 조회"에 대해 corrupt 문서보다 먼저 돌려줄 다른
        # 후보들 - 실제 4,818건 코퍼스에서는 이런 다른 후보가 항상 있다. 후보가 하나도
        # 없는 작은 테스트 인덱스에서는 최후 수단(exclude_status 해제)이 곧바로 실행돼
        # corrupt 문서를 찾아버리므로, "후보가 있지만 corrupt는 아니다"를 재현하려면
        # 이 채워넣기 문서들이 필요하다.
        *[_record(f"filler-{i}", "손상된 문서 접수번호 조회와 무관한 채워넣기") for i in range(5)],
    ])
    yield idx
    idx.close()


def test_native_id_map_reverses_concept_id_to_original_doc_id(index) -> None:
    mapping = native_id_map(index)
    assert mapping == {"native-a": "concept-a", "native-b": "concept-b",
                       "native-c": "concept-corrupt"}


def test_resolve_gold_falls_back_to_the_raw_id_when_unmapped() -> None:
    assert resolve_gold("native-a", {"native-a": "concept-a"}) == "concept-a"
    assert resolve_gold("unknown-id", {"native-a": "concept-a"}) == "unknown-id"


def test_score_finds_the_mapped_gold_document(index) -> None:
    retriever = AdaptiveRetriever(index, EntityLexicon.__new__(EntityLexicon))
    retriever.lex.by_name = {}
    queries = [{"qid": "q1", "query": "에이피알 실적", "gold_doc": "native-a",
               "source_type": "telegram"}]
    result = score(index, retriever, queries)
    assert result["recall@10"] == 1.0
    assert result["hit@1"] == 1.0
    assert result["misses"] == []


def test_score_reports_a_miss_when_the_gold_document_is_not_found(index) -> None:
    retriever = AdaptiveRetriever(index, EntityLexicon.__new__(EntityLexicon))
    retriever.lex.by_name = {}
    queries = [{"qid": "q1", "query": "에이피알 실적", "gold_doc": "native-b",
               "source_type": "telegram"}]
    result = score(index, retriever, queries)
    assert result["recall@10"] == 0.0
    assert result["misses"] == [{"qid": "q1", "query": "에이피알 실적"}]


def test_score_excludes_corrupt_gold_documents_by_default(index) -> None:
    """정답 문서가 corrupt로 표시돼 있으면 기본 설정에서는 찾지 못한다 - 버그가 아니라
    "읽을 수 없는 문서는 근거로 안 쓴다"는 정책이 그대로 적용된 것이다. 실제 DART
    2013/2010년 필링 질의(D-005~D-008)가 정확히 이 경로로 실패한다."""
    retriever = AdaptiveRetriever(index, EntityLexicon.__new__(EntityLexicon))
    retriever.lex.by_name = {}
    queries = [{"qid": "q1", "query": "손상된 문서", "gold_doc": "native-c",
               "source_type": "dart"}]
    result = score(index, retriever, queries)
    assert result["recall@10"] == 0.0


def test_score_breaks_down_recall_by_source_type(index) -> None:
    retriever = AdaptiveRetriever(index, EntityLexicon.__new__(EntityLexicon))
    retriever.lex.by_name = {}
    queries = [
        {"qid": "q1", "query": "에이피알 실적", "gold_doc": "native-a", "source_type": "telegram"},
        {"qid": "q2", "query": "존재하지않는것", "gold_doc": "native-x", "source_type": "dart"},
    ]
    result = score(index, retriever, queries)
    assert result["by_source_type"]["telegram"] == {"n": 1, "recall@10": 1.0}
    assert result["by_source_type"]["dart"] == {"n": 1, "recall@10": 0.0}


def test_unmapped_gold_ids_are_counted_separately_from_misses(index) -> None:
    """매핑 실패(native_doc_id 자체가 인덱스에 없음)와 검색 실패(있지만 못 찾음)는
    다른 문제다 - 하나로 뭉치면 원인 진단이 안 된다."""
    retriever = AdaptiveRetriever(index, EntityLexicon.__new__(EntityLexicon))
    retriever.lex.by_name = {}
    queries = [{"qid": "q1", "query": "무관", "gold_doc": "no-such-native-id",
               "source_type": "dart"}]
    result = score(index, retriever, queries)
    assert result["unmapped_gold"] == 1

"""벡터 인덱스와 Hybrid Search 테스트.

모델 가중치가 없어도 전부 돌아가게 `HashEncoder`를 쓴다. 여기서 확인하는 것은
'뜻을 잘 알아듣는가'가 아니라 '파이프라인이 설계대로 도는가'다. 검색 품질은
평가셋으로 재는 것이지 단위 테스트로 재는 것이 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from investor_intel.indexing.embedding import HashEncoder, load_encoder
from investor_intel.indexing.hybrid import HybridSearcher, rrf_fuse
from investor_intel.indexing.vector_index import VectorIndex
from investor_intel.indexing.vector_pipeline import VectorScope, coverage_report, resolve_gold


@dataclass
class FakeConcept:
    status: str
    body_text: str

    @property
    def has_body(self) -> bool:
        return self.status != "stub" and bool(self.body_text.strip())

    @property
    def body(self) -> str:
        return self.body_text


@dataclass
class FakeHit:
    doc_id: str
    title: str = ""
    text: str = ""
    source_type: str = ""
    okf_status: str = ""
    entity_key: str = ""
    period_year: str = ""
    kind: str = ""


def _records():
    rows = [
        ("a#0", "a", "삼성전자 반도체 설비투자 계획", "stable", "|kr-005930|", "2026"),
        ("a#1", "a", "메모리 가격 반등 전망", "stable", "|kr-005930|", "2026"),
        ("b#0", "b", "에이피알 목표주가 상향", "stable", "|kr-278470|", "2026"),
        ("c#0", "c", "삼성전자 2010년 분기보고서 요약", "stable", "|kr-005930|", "2010"),
    ]
    for uid, doc, text, status, ent, year in rows:
        yield {
            "embed_text": text, "chunk_uid": uid, "doc_id": doc, "ord": int(uid[-1]),
            "title": text[:10], "source_type": "test", "okf_type": "ResearchNote",
            "entity_key": ent, "period_year": year, "pub_year": year,
            "okf_status": status, "heading": "", "n_chars": len(text), "raw_text": text,
        }


@pytest.fixture()
def built(tmp_path):
    index = VectorIndex(tmp_path / "v.sqlite3")
    stats = index.build(_records(), HashEncoder(), batch_size=2)
    return index, stats


# --------------------------------------------------------------- 인코더

def test_encoder_vectors_are_unit_length():
    enc = HashEncoder()
    vecs = enc.encode_passages(["삼성전자 반도체", "에이피알 목표주가"])
    lengths = np.linalg.norm(vecs, axis=1)
    assert np.allclose(lengths, 1.0, atol=1e-5)


def test_encoder_is_deterministic():
    """같은 글은 늘 같은 벡터여야 한다. 아니면 평가 결과를 재현할 수 없다."""
    a = HashEncoder().encode_passages(["삼성전자 반도체 설비투자"])
    b = HashEncoder().encode_passages(["삼성전자 반도체 설비투자"])
    assert np.allclose(a, b)


def test_empty_text_does_not_crash():
    assert HashEncoder().encode_passages([]).shape[0] == 0
    assert HashEncoder().encode_passages(["", "  "]).shape == (2, 256)


def test_load_encoder_rejects_unknown_model():
    with pytest.raises(ValueError):
        load_encoder("이런-모델-없음")


# ---------------------------------------------------------- 벡터 인덱스

def test_build_stores_every_chunk(built):
    index, stats = built
    assert stats.chunks_embedded == 4
    assert stats.docs_embedded == 3
    assert index.matrix.shape[0] == 4


def test_empty_embed_text_is_skipped(tmp_path):
    index = VectorIndex(tmp_path / "v.sqlite3")
    rows = list(_records())
    rows.append({**rows[0], "chunk_uid": "z#0", "doc_id": "z", "embed_text": "   "})
    stats = index.build(rows, HashEncoder())
    assert stats.chunks_skipped == 1
    assert "z" not in index.covered_docs()


def test_search_returns_ranked_hits(built):
    index, _ = built
    hits = index.search("삼성전자 반도체 설비투자 계획", HashEncoder(), k=3)
    assert hits
    assert hits[0].doc_id == "a"
    assert hits[0].score >= hits[-1].score


def test_entity_filter_narrows_candidates(built):
    index, _ = built
    hits = index.search("설비투자", HashEncoder(), k=10, entity_key="kr-278470")
    assert {h.doc_id for h in hits} == {"b"}


def test_period_filter_narrows_candidates(built):
    index, _ = built
    hits = index.search("삼성전자", HashEncoder(), k=10, period_year="2010")
    assert {h.doc_id for h in hits} == {"c"}


def test_filter_with_no_match_returns_empty(built):
    index, _ = built
    assert index.search("삼성전자", HashEncoder(), k=5, entity_key="kr-999999") == []


def test_search_documents_keeps_one_chunk_per_doc(built):
    """문서 하나가 상위를 다 차지하면 후보 다양성이 죽는다. BM25 쪽과 규칙을 맞춘다."""
    index, _ = built
    hits = index.search_documents("삼성전자 반도체 메모리", HashEncoder(), k=5)
    assert len({h.doc_id for h in hits}) == len(hits)


# ------------------------------------------------------------------ RRF

def test_rrf_prefers_documents_found_by_both():
    bm = [FakeHit("x"), FakeHit("y")]
    vec = [FakeHit("y"), FakeHit("z")]
    fused = rrf_fuse(bm, vec, k=3)
    assert fused[0].doc_id == "y"
    assert fused[0].found_by == ("bm25", "vector")


def test_rrf_keeps_documents_found_by_only_one_side():
    """V4 사건의 재발 방지선. 한쪽에만 잡힌 문서가 사라지면 안 된다."""
    bm = [FakeHit("only_bm25")]
    vec = [FakeHit("only_vector")]
    ids = {h.doc_id for h in rrf_fuse(bm, vec, k=5)}
    assert ids == {"only_bm25", "only_vector"}


def test_rrf_marks_which_side_found_it():
    fused = {h.doc_id: h for h in rrf_fuse([FakeHit("p")], [FakeHit("q")], k=5)}
    assert fused["p"].only_bm25 and not fused["p"].only_vector
    assert fused["q"].only_vector and not fused["q"].only_bm25


def test_rrf_weight_zero_disables_one_side():
    fused = rrf_fuse([FakeHit("p")], [FakeHit("q")], k=5, vector_weight=0.0)
    assert fused[0].doc_id == "p"
    assert fused[0].score > 0


def test_rrf_ordering_is_stable():
    """점수가 같을 때 순서가 흔들리면 평가 결과를 믿을 수 없다."""
    bm = [FakeHit("m"), FakeHit("n")]
    vec = [FakeHit("n"), FakeHit("m")]
    first = [h.doc_id for h in rrf_fuse(bm, vec, k=5)]
    for _ in range(5):
        assert [h.doc_id for h in rrf_fuse(bm, vec, k=5)] == first


class FakeBm25:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def search_documents(self, query, k=10, **filters):
        self.calls.append((query, filters))
        return self.hits[:k]


def test_hybrid_falls_back_to_bm25_when_vectors_missing():
    bm = FakeBm25([FakeHit("a"), FakeHit("b")])
    searcher = HybridSearcher(bm, None, None)
    assert not searcher.vector_enabled
    assert [h.doc_id for h in searcher.search("질문", k=2)] == ["a", "b"]


def test_min_vector_score_drops_weak_vector_hits(built):
    """유사도가 낮은 벡터 결과까지 섞으면 BM25 1등이 밀려난다."""
    index, _ = built
    bm = FakeBm25([FakeHit("a")])
    loose = HybridSearcher(bm, index, HashEncoder(), pool=10)
    strict = HybridSearcher(bm, index, HashEncoder(), pool=10, min_vector_score=0.99)
    assert len(loose.search("에이피알 목표주가", k=5)) > 1
    assert [h.doc_id for h in strict.search("에이피알 목표주가", k=5)] == ["a"]


def test_vector_top_limits_how_many_get_mixed(built):
    index, _ = built
    bm = FakeBm25([FakeHit("a")])
    searcher = HybridSearcher(bm, index, HashEncoder(), pool=10, vector_top=1)
    assert len(searcher.search("삼성전자 반도체", k=5)) <= 2


def test_hybrid_passes_same_filters_to_both_sides(built):
    """한쪽에만 필터를 걸면 걸러졌어야 할 문서가 다른 쪽 순위를 타고 올라온다."""
    index, _ = built
    bm = FakeBm25([FakeHit("b")])
    searcher = HybridSearcher(bm, index, HashEncoder(), pool=10)
    hits = searcher.search("설비투자", k=5, entity_key="kr-278470")
    assert bm.calls[0][1]["entity_key"] == "kr-278470"
    assert {h.doc_id for h in hits} == {"b"}


# -------------------------------------------------------- 대상 범위 확인

@pytest.mark.parametrize("status,body,expected", [
    ("stable", "본문이 충분히 길게 들어 있는 경우입니다", True),
    ("stub", "본문이 충분히 길게 들어 있는 경우입니다", False),
    ("corrupt", "본문이 충분히 길게 들어 있는 경우입니다", False),
    ("superseded", "본문이 충분히 길게 들어 있는 경우입니다", False),
    ("stable", "짧음", False),
])
def test_scope_accepts_only_stable_with_body(status, body, expected):
    ok, _ = VectorScope().accepts(FakeConcept(status, body))
    assert ok is expected


def test_scope_reason_is_recorded():
    ok, reason = VectorScope().accepts(FakeConcept("corrupt", "본문이 여기 충분히 들어 있습니다"))
    assert not ok and reason == "status:corrupt"


def test_resolve_gold_uses_native_index():
    assert resolve_gold({"gold_doc": "abc"}, {"abc": "2026-01-01-abc"}) == "2026-01-01-abc"
    assert resolve_gold({"gold_doc": "abc"}, {}) == "abc"
    assert resolve_gold({"gold_concept": "X", "gold_doc": "abc"}, {"abc": "Y"}) == "X"


def test_coverage_report_counts_by_axis():
    items = [
        {"qid": "1", "gold_doc": "a", "axis": "dart"},
        {"qid": "2", "gold_doc": "b", "axis": "dart"},
        {"qid": "3", "gold_doc": "c", "axis": "telegram"},
    ]
    rep = coverage_report({"a", "c"}, items)
    assert rep["by_axis"]["dart"]["gold_not_embedded"] == 1
    assert rep["by_axis"]["telegram"]["gold_not_embedded"] == 0
    assert rep["total_gold_not_embedded"] == 1


# --- FusedHit이 OKF 메타데이터를 잃지 않는지 --------------------------------------------
# rrf_fuse가 title/text/source_type만 옮기던 시절에는, 순위를 합친 뒤 corrupt 문서를
# 걸러내거나(exclude_status) 재랭킹에 entity_key를 쓸 방법이 없었다.


def test_rrf_fuse_carries_okf_metadata_through() -> None:
    bm = [FakeHit("p", okf_status="corrupt", entity_key="|kr-005930|", kind="table")]
    vec = [FakeHit("q", okf_status="stable", period_year="2026")]
    fused = {h.doc_id: h for h in rrf_fuse(bm, vec, k=5)}
    assert fused["p"].okf_status == "corrupt"
    assert fused["p"].entity_key == "|kr-005930|"
    assert fused["p"].kind == "table"
    assert fused["q"].okf_status == "stable"
    assert fused["q"].period_year == "2026"


def test_hybrid_searcher_exposes_search_documents_alias(built) -> None:
    """AdaptiveRetriever가 BM25 단독/Hybrid 어느 쪽이든 같은 메서드 이름으로 부를 수 있다."""
    index, _ = built
    bm = FakeBm25([FakeHit("a"), FakeHit("b")])
    searcher = HybridSearcher(bm, index, HashEncoder(), pool=10)
    via_alias = searcher.search_documents("삼성전자", k=3)
    via_search = searcher.search("삼성전자", k=3)
    assert [h.doc_id for h in via_alias] == [h.doc_id for h in via_search]

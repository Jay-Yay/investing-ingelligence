"""글자 검색과 뜻 검색을 합치는 부분.

두 검색은 점수 체계가 다르다. BM25는 값이 작을수록 좋고 범위도 정해져 있지 않다.
코사인 유사도는 -1에서 1 사이이고 클수록 좋다. 이 둘을 그냥 더하면 한쪽이 다른 쪽을
잡아먹는다. 그래서 점수 대신 순위만 쓴다. 이것이 RRF(Reciprocal Rank Fusion)다.

    점수(문서) = Σ  가중치 / (k + 그 검색에서의 등수)

k는 보통 60을 쓴다. 1등과 2등의 차이를 너무 크게 벌리지 않으려고 넣는 완충값이다.
k가 작으면 1등이 거의 모든 것을 결정하고, k가 크면 두 검색의 의견이 고르게 섞인다.

이 방식의 장점은 한쪽에만 잡힌 문서도 자연스럽게 살아남는다는 것이다. 접수번호로
찾는 공시처럼 본문이 없어서 벡터를 안 만든 문서는 BM25에서만 나오는데, RRF는
합집합을 다루므로 그대로 후보에 남는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

RRF_K = 60


@dataclass
class FusedHit:
    doc_id: str
    score: float
    title: str = ""
    text: str = ""
    source_type: str = ""
    bm25_rank: int | None = None
    vector_rank: int | None = None
    found_by: tuple[str, ...] = field(default_factory=tuple)

    @property
    def only_vector(self) -> bool:
        return self.bm25_rank is None and self.vector_rank is not None

    @property
    def only_bm25(self) -> bool:
        return self.vector_rank is None and self.bm25_rank is not None


def rrf_fuse(
    bm25_hits: Sequence,
    vector_hits: Sequence,
    k: int = 10,
    *,
    rrf_k: int = RRF_K,
    bm25_weight: float = 1.0,
    vector_weight: float = 1.0,
) -> list[FusedHit]:
    """두 결과 목록을 등수로 합친다. 각 목록은 문서 단위로 접혀 있어야 한다."""
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}
    bm_rank: dict[str, int] = {}
    vec_rank: dict[str, int] = {}

    for rank, hit in enumerate(bm25_hits, start=1):
        doc = hit.doc_id
        scores[doc] = scores.get(doc, 0.0) + bm25_weight / (rrf_k + rank)
        bm_rank.setdefault(doc, rank)
        meta.setdefault(doc, {
            "title": getattr(hit, "title", "") or "",
            "text": getattr(hit, "text", "") or "",
            "source_type": getattr(hit, "source_type", "") or "",
        })

    for rank, hit in enumerate(vector_hits, start=1):
        doc = hit.doc_id
        scores[doc] = scores.get(doc, 0.0) + vector_weight / (rrf_k + rank)
        vec_rank.setdefault(doc, rank)
        meta.setdefault(doc, {
            "title": getattr(hit, "title", "") or "",
            "text": getattr(hit, "text", "") or "",
            "source_type": getattr(hit, "source_type", "") or "",
        })

    fused = [
        FusedHit(
            doc_id=doc,
            score=score,
            title=meta[doc]["title"],
            text=meta[doc]["text"],
            source_type=meta[doc]["source_type"],
            bm25_rank=bm_rank.get(doc),
            vector_rank=vec_rank.get(doc),
            found_by=tuple(x for x in (
                "bm25" if doc in bm_rank else None,
                "vector" if doc in vec_rank else None) if x),
        )
        for doc, score in scores.items()
    ]
    # 점수가 같으면 BM25 등수가 앞선 쪽을 먼저 둔다. 실행할 때마다 순서가 바뀌면
    # 평가 결과를 신뢰할 수 없다.
    fused.sort(key=lambda h: (-h.score, h.bm25_rank if h.bm25_rank else 10**6, h.doc_id))
    return fused[:k]


class HybridSearcher:
    """BM25 인덱스와 벡터 인덱스를 같은 조건으로 두드리고 결과를 합친다.

    메타데이터 필터는 양쪽 공통 전처리로 그대로 넘긴다. 한쪽에만 필터를 걸면
    합칠 때 기준이 어긋나서, 걸러졌어야 할 문서가 다른 쪽 순위를 타고 올라온다.
    """

    def __init__(self, bm25_index, vector_index=None, encoder=None, *,
                 bm25_weight: float = 1.0, vector_weight: float = 1.0,
                 rrf_k: int = RRF_K, pool: int = 100,
                 min_vector_score: float = 0.0, vector_top: int | None = None):
        self.bm25 = bm25_index
        self.vectors = vector_index
        self.encoder = encoder
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.rrf_k = rrf_k
        self.pool = pool
        # RRF는 두 검색이 각자 어느 정도는 쓸 만하다는 것을 전제로 한다. 한쪽이 엉망이면
        # 양쪽에 어중간하게 걸린 문서가 한쪽에서 1등인 문서를 이겨서 결과가 오히려 나빠진다.
        # 아래 두 손잡이가 그 상황을 막는 장치다.
        #   min_vector_score  유사도가 이 값보다 낮은 벡터 결과는 아예 안 섞는다
        #   vector_top        벡터 쪽에서 상위 몇 개까지만 섞을지
        self.min_vector_score = min_vector_score
        self.vector_top = vector_top

    @property
    def vector_enabled(self) -> bool:
        return self.vectors is not None and self.encoder is not None

    def search(self, query: str, k: int = 10, **filters) -> list[FusedHit]:
        bm_hits = self.bm25.search_documents(query, k=self.pool, **filters)
        if not self.vector_enabled:
            return rrf_fuse(bm_hits, [], k=k, rrf_k=self.rrf_k,
                            bm25_weight=self.bm25_weight, vector_weight=0.0)
        vec_hits = self.vectors.search_documents(query, self.encoder, k=self.pool, **filters)
        if self.min_vector_score:
            vec_hits = [h for h in vec_hits if h.score >= self.min_vector_score]
        if self.vector_top is not None:
            vec_hits = vec_hits[: self.vector_top]
        return rrf_fuse(bm_hits, vec_hits, k=k, rrf_k=self.rrf_k,
                        bm25_weight=self.bm25_weight, vector_weight=self.vector_weight)

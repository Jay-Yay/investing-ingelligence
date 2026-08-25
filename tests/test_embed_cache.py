from __future__ import annotations

from pathlib import Path

import numpy as np

from investor_intel.indexing.embed_cache import CachedEncoder, EmbeddingCache, text_hash
from investor_intel.indexing.embedding import HashEncoder


class CountingEncoder:
    """인코딩 호출 횟수를 세는 래퍼. 캐시가 실제로 호출을 줄이는지 보려면 필요하다."""

    def __init__(self, dim: int = 32, name: str = "counting") -> None:
        self._inner = HashEncoder(dim=dim)
        self.name = name
        self.dim = dim
        self.encoded = 0

    def encode_passages(self, texts):
        self.encoded += len(texts)
        return self._inner.encode_passages(texts)

    def encode_queries(self, texts):
        return self._inner.encode_queries(texts)


def _cached(tmp_path: Path, dim: int = 32, name: str = "counting"):
    cache = EmbeddingCache(tmp_path / "cache.sqlite3")
    inner = CountingEncoder(dim=dim, name=name)
    return CachedEncoder(inner, cache), inner, cache


def test_second_pass_encodes_nothing(tmp_path: Path) -> None:
    """임베딩은 이 파이프라인에서 가장 비싼 단계다. 내용이 같으면 다시 계산할 이유가 없다."""
    encoder, inner, cache = _cached(tmp_path)
    texts = ["첫 조각", "둘째 조각", "셋째 조각"]

    first = encoder.encode_passages(texts)
    assert inner.encoded == 3
    assert encoder.stats.misses == 3 and encoder.stats.hits == 0

    second = encoder.encode_passages(texts)
    assert inner.encoded == 3                       # 새로 인코딩한 것이 없다
    assert encoder.stats.hits == 3
    np.testing.assert_array_equal(first, second)
    cache.close()


def test_only_the_changed_chunks_are_encoded(tmp_path: Path) -> None:
    """문서에 한 문장을 덧붙였을 때 그 문서의 모든 청크를 다시 인코딩하지 않는다."""
    encoder, inner, cache = _cached(tmp_path)
    encoder.encode_passages(["A", "B", "C"])
    assert inner.encoded == 3

    encoder.encode_passages(["A", "B", "C", "D"])
    assert inner.encoded == 4                       # D 하나만 추가로 인코딩됐다
    cache.close()


def test_vector_order_follows_the_input_even_with_duplicates(tmp_path: Path) -> None:
    encoder, _, cache = _cached(tmp_path)
    out = encoder.encode_passages(["같은 조각", "다른 조각", "같은 조각"])
    assert out.shape == (3, 32)
    np.testing.assert_array_equal(out[0], out[2])
    assert not np.array_equal(out[0], out[1])
    cache.close()


def test_a_different_model_does_not_reuse_vectors(tmp_path: Path) -> None:
    """모델을 바꾸면 벡터 공간 자체가 달라져 섞어 쓸 수 없다."""
    cache = EmbeddingCache(tmp_path / "cache.sqlite3")
    first = CachedEncoder(CountingEncoder(name="model-a"), cache)
    first.encode_passages(["조각"])

    second_inner = CountingEncoder(name="model-b")
    CachedEncoder(second_inner, cache).encode_passages(["조각"])
    assert second_inner.encoded == 1
    cache.close()


def test_dimension_mismatch_is_treated_as_a_miss(tmp_path: Path) -> None:
    """같은 모델 이름으로 차원이 다른 벡터가 섞이면 행렬 곱에서 조용히 깨진다."""
    cache = EmbeddingCache(tmp_path / "cache.sqlite3")
    CachedEncoder(CountingEncoder(dim=16, name="same"), cache).encode_passages(["조각"])

    wider_inner = CountingEncoder(dim=64, name="same")
    out = CachedEncoder(wider_inner, cache).encode_passages(["조각"])
    assert wider_inner.encoded == 1
    assert out.shape == (1, 64)
    cache.close()


def test_cache_survives_reopening_the_file(tmp_path: Path) -> None:
    encoder, _, cache = _cached(tmp_path)
    encoder.encode_passages(["조각"])
    cache.close()

    reopened = EmbeddingCache(tmp_path / "cache.sqlite3")
    inner = CountingEncoder(name="counting")
    CachedEncoder(inner, reopened).encode_passages(["조각"])
    assert inner.encoded == 0
    reopened.close()


def test_queries_are_not_cached(tmp_path: Path) -> None:
    """질의는 매번 다른 문장이라 적중률이 사실상 0이면서 캐시만 부풀린다."""
    encoder, _, cache = _cached(tmp_path)
    encoder.encode_queries(["질문"])
    assert cache.size() == 0
    cache.close()


def test_text_hash_is_stable_and_content_addressed() -> None:
    assert text_hash("같은 글") == text_hash("같은 글")
    assert text_hash("같은 글") != text_hash("다른 글")

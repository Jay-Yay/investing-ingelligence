"""글의 뜻을 숫자로 바꾸는 부분.

BM25는 글자가 겹쳐야 찾는다. 문서에 "보유 종목 수"라고 적혀 있는데 "편입 종목 개수"로
물으면 겹치는 글자가 없어서 못 찾는다. 실측으로도 사람이 쓴 질문 24건 중 8건이 이
이유로 전 변형에서 실패했다. 그 8건을 겨냥해서 붙이는 것이 이 모듈이다.

설계에서 신경 쓴 것 두 가지.

1) 모델을 갈아끼울 수 있게 인터페이스만 정해 두었다. 로컬 모델이든 API든 `Encoder`
   프로토콜만 만족하면 된다. 모델 가중치를 못 받는 환경에서도 `HashEncoder`로
   파이프라인 전체를 테스트할 수 있다.
2) e5 계열은 질의에 "query: ", 문서에 "passage: " 접두어를 붙여야 성능이 난다.
   이걸 호출부에 맡기면 반드시 한쪽을 빠뜨리므로 인코더가 스스로 붙인다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol, Sequence

import numpy as np


class Encoder(Protocol):
    """문장 여러 개를 받아 정규화된 벡터 행렬을 돌려준다."""

    name: str
    dim: int

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray: ...

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray: ...


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    """길이를 1로 맞춘다.

    이렇게 해 두면 코사인 유사도가 그냥 내적이 되어서, 검색할 때 행렬 곱 한 번으로
    끝난다. 조각 5만 개 정도는 이 방식으로 충분히 빠르다.
    """
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (mat / norms).astype(np.float32)


# 이 코퍼스는 한국어 3,977건과 영어 841건이 섞여 있어서 다국어 모델이어야 한다.
# 접두어 규칙이 모델마다 달라서 같이 적어 둔다.
MODEL_PRESETS: dict[str, dict] = {
    "multilingual-e5-large": {
        "repo": "intfloat/multilingual-e5-large",
        "dim": 1024,
        "query_prefix": "query: ",
        "passage_prefix": "passage: ",
        "note": "한국어 성능이 안정적이고 접두어 규칙이 명확하다. 기본값으로 둔다.",
    },
    "multilingual-e5-base": {
        "repo": "intfloat/multilingual-e5-base",
        "dim": 768,
        "query_prefix": "query: ",
        "passage_prefix": "passage: ",
        "note": "메모리가 부족하거나 먼저 빠르게 확인만 해보고 싶을 때.",
    },
    "bge-m3": {
        "repo": "BAAI/bge-m3",
        "dim": 1024,
        "query_prefix": "",
        "passage_prefix": "",
        "note": "긴 문서에 강하고 접두어가 필요 없다. 다만 모델이 크다.",
    },
}

DEFAULT_MODEL = "multilingual-e5-large"


@dataclass
class LocalEncoder:
    """로컬에 받아 둔 모델로 직접 계산한다. API 키가 필요 없다.

    한 번 계산해 두면 다시 색인할 때만 재계산하면 되므로, 개인용 도구에서는 이쪽이
    API보다 다루기 편하다. 대신 모델 가중치를 미리 받아 둬야 한다.
    """

    model_key: str = DEFAULT_MODEL
    batch_size: int = 32
    device: str | None = None
    max_seq_length: int = 512
    _model: object | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.model_key not in MODEL_PRESETS:
            raise ValueError(
                f"모르는 모델입니다: {self.model_key}. "
                f"쓸 수 있는 것: {', '.join(MODEL_PRESETS)}"
            )
        self.preset = MODEL_PRESETS[self.model_key]
        self.name = self.model_key
        self.dim = int(self.preset["dim"])

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "sentence-transformers가 없습니다. "
                    "`uv pip install sentence-transformers` 후에 다시 실행해 주세요."
                ) from exc
            model = SentenceTransformer(self.preset["repo"], device=self.device)
            model.max_seq_length = self.max_seq_length
            self._model = model
        return self._model

    def _encode(self, texts: Sequence[str], prefix: str) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        model = self._load()
        payload = [prefix + t for t in texts] if prefix else list(texts)
        vecs = model.encode(
            payload,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=False,
        )
        return _l2_normalize(np.asarray(vecs, dtype=np.float32))

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts, self.preset["passage_prefix"])

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts, self.preset["query_prefix"])


@dataclass
class ApiEncoder:
    """임베딩 API를 쓰는 경우.

    로컬 모델을 못 돌리는 환경을 위한 대안이다. 키는 환경변수로 받는다. 요청 실패 시
    조용히 0 벡터를 넣으면 검색 결과가 조용히 나빠지므로, 실패하면 그냥 예외를 낸다.
    """

    provider: str = "openai"
    model: str = "text-embedding-3-large"
    dim: int = 3072
    batch_size: int = 128
    api_key_env: str = "OPENAI_API_KEY"

    def __post_init__(self) -> None:
        self.name = f"{self.provider}:{self.model}"

    def _client(self):
        import os

        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(f"{self.api_key_env} 환경변수가 비어 있습니다.")
        if self.provider != "openai":
            raise NotImplementedError(f"{self.provider}는 아직 안 붙였습니다.")
        from openai import OpenAI

        return OpenAI(api_key=key)

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        client = self._client()
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = [t.replace("\n", " ") for t in texts[i: i + self.batch_size]]
            resp = client.embeddings.create(model=self.model, input=batch)
            out.extend(d.embedding for d in resp.data)
        return _l2_normalize(np.asarray(out, dtype=np.float32))

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts)

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts)


@dataclass
class HashEncoder:
    """테스트용 가짜 인코더. 모델을 안 받아도 파이프라인 전체가 돌아간다.

    글자 3-gram을 해시해서 고정 길이 벡터에 흩뿌린다. 뜻을 알아듣지는 못하지만
    '같은 글이면 같은 벡터, 겹치는 글자가 많으면 가까운 벡터'는 성립해서, 인덱스
    저장·필터·RRF 합치기가 제대로 도는지 확인하는 데는 충분하다.

    실험 결과를 이걸로 내면 안 된다. 그건 BM25를 벡터인 척 포장한 것에 불과하다.
    """

    dim: int = 256
    name: str = "hash-3gram"

    def _one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        s = text.strip()
        if not s:
            return vec
        for i in range(max(1, len(s) - 2)):
            gram = s[i: i + 3]
            h = int.from_bytes(hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(), "big")
            vec[h % self.dim] += 1.0
        return vec

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _l2_normalize(np.stack([self._one(t) for t in texts]))

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts)

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts)


def load_encoder(spec: str = DEFAULT_MODEL, **kwargs) -> Encoder:
    """이름 하나로 인코더를 고른다.

    `hash`  테스트용 가짜
    `api:...`  임베딩 API
    그 외  MODEL_PRESETS의 로컬 모델 이름
    """
    if spec == "hash":
        return HashEncoder(**kwargs)
    if spec.startswith("api:"):
        return ApiEncoder(model=spec[4:], **kwargs)
    return LocalEncoder(model_key=spec, **kwargs)

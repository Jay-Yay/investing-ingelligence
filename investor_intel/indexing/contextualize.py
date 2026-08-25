from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# Anthropic "Contextual Retrieval" 원안 프롬프트 (engineering 블로그 게재본 그대로).
# 문서 전체와 청크를 함께 넣고 '이 청크가 문서 안에서 무엇인지' 50~100 토큰으로 쓰게 한다.
GENERATIVE_PROMPT = """<document>
{whole_document}
</document>
Here is the chunk we want to situate within the whole document
<chunk>
{chunk_content}
</chunk>
Please give a short succinct context to situate this chunk within the overall document for \
the purposes of improving search retrieval of the chunk. Answer only with the succinct context \
and nothing else."""


class Contextualizer(Protocol):
    def context_for(self, whole_document: str, chunk: str, metadata: dict) -> str: ...


@dataclass
class MetadataProjection:
    """OKF concept의 description을 그대로 청크 문맥으로 쓴다(비용 0, 결정론적).

    원안과의 차이를 분명히 해둔다.
      - 원안: 문서 전체를 LLM에 넣어 '이 청크가 문서 안에서 무엇인지'를 생성한다.
        문서마다, 청크마다 다른 문장이 나오고, 문서의 논지 안에서의 위치까지 담긴다.
      - 이 구현: concept의 확정된 메타데이터(출처·종목·유형·기간·제목)를 조립한다.
        같은 문서의 모든 청크가 같은 문맥을 받는다. 청크 사이의 차이는 담지 못한다.
    이 코퍼스에서 이 대체가 성립하는 이유는 수집기가 이미 구조화된 메타데이터를 붙여두기
    때문이다. 메타데이터가 없는 코퍼스(코드베이스, 소설, 스크랩한 웹문서)에서는 성립하지 않는다.
    """

    include_tags: bool = True

    def context_for(self, whole_document: str, chunk: str, metadata: dict) -> str:
        ctx = str(metadata.get("description") or "")
        if self.include_tags and metadata.get("tags"):
            ctx = f"{ctx} [{' '.join(metadata['tags'])}]"
        return ctx.strip()


@dataclass
class GenerativeContextualizer:
    """원안 그대로의 생성형 문맥 부여.

    이 저장소에는 이미 LLM 클라이언트(`investor_intel.llm.client`)와 비용 상한
    (`DAILY_LLM_BUDGET_USD`)이 있으므로 그대로 얹으면 된다. 원문 기준 비용은 프롬프트
    캐싱 적용 시 문서 100만 토큰당 $1.02이다. 이 코퍼스는 약 2,680만 자
    (한국어 기준 대략 1,300만~1,800만 토큰)라 1회 전량 처리에 $13~18 규모가 된다.

    측정하지 않은 것을 측정한 것처럼 쓰지 않기 위해 밝혀둔다: 5주차 실습에서는 이 경로를
    실행하지 않았다. API 키 없이 돌린 것은 MetadataProjection 쪽이다.
    """

    client: object | None = None
    model: str = "claude-haiku-4-5"
    max_tokens: int = 150

    def context_for(self, whole_document: str, chunk: str, metadata: dict) -> str:
        if self.client is None:
            raise RuntimeError(
                "GenerativeContextualizer에 LLM 클라이언트가 없다. "
                "investor_intel.llm.client를 주입하거나 MetadataProjection을 쓸 것.")
        prompt = GENERATIVE_PROMPT.format(
            whole_document=whole_document[:180_000], chunk_content=chunk)
        return self.client.complete(  # type: ignore[attr-defined]
            prompt, model=self.model, max_tokens=self.max_tokens).strip()


def estimate_generative_cost(total_chars: int, chunk_chars: int = 700,
                             usd_per_million_doc_tokens: float = 1.02,
                             chars_per_token: float = 1.7) -> dict:
    """원안이 공개한 단가로 전량 처리 비용을 추정한다(프롬프트 캐싱 가정)."""
    doc_tokens = total_chars / chars_per_token
    return {
        "chunks": round(total_chars / chunk_chars),
        "document_tokens_est": round(doc_tokens),
        "usd_est": round(doc_tokens / 1_000_000 * usd_per_million_doc_tokens, 2),
    }

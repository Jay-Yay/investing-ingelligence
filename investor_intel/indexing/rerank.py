"""후보 상위 N개만 다시 정렬하는 결정론적 reranker.

## 왜 결정론적인가

노션 문서(§8)가 인용한 Anthropic 원안은 cross-encoder reranker로 Top-20 실패율을
2.9% → 1.9%까지 낮췄다(Contextual Embedding + BM25 대비 34% 추가 감소). 그 수치는
학습된 모델 기준이라 규칙 기반 reranker가 같은 감소폭을 낼 근거는 없다. 여기서 하는
것은 그 모델을 대체하는 것이 아니라, **필터로 못 거른 신호를 순위에 반영하는 것**이다.

구체적으로 지금 비어 있는 자리 하나: `entity_key`가 `AdaptiveRetriever`에서
**필터로만** 쓰이고 순위에는 전혀 반영되지 않는다. "교보증권이 제시한 에이피알
목표주가" 실패 사례(교보증권의 다른 종목 리포트가 상위 5위를 독점)가 정확히 순위
문제였다 - 필터 자체가 없던 시절의 실패지만, 지금도 필터가 relax되는 완화 루프
안에서는 같은 패턴이 재발할 수 있다.

## 원본 순위를 존중한다

BM25 점수와 RRF 점수는 스케일이 다르고(그래서 RRF가 순위만 쓰도록 설계됐다), 여기서
새 점수를 만들어 원본 점수와 섞으면 그 문제를 다시 만든다. 그래서 이 reranker는
**원본 순위를 그대로 tie-break로 두고, 보너스가 있는 히트만 앞으로 당긴다** - 점수를
새로 계산하지 않고 안정 정렬(stable sort)로 재배치만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RerankSignal:
    """어떤 신호에 얼마나 가중치를 줄지. 값이 클수록 그 신호가 순위를 더 강하게 당긴다."""

    entity_match: float = 2.0     # 질의가 지목한 종목과 entity_key가 일치
    period_match: float = 1.0     # 질의의 연도와 period_year(또는 pub_year)가 일치
    prefer_table: float = 1.5     # 숫자 질의인데 kind='table'인 청크
    status_penalty: float = -3.0  # stable이 아닌 상태(corrupt/stub/superseded)


DEFAULT_SIGNAL = RerankSignal()

# "총", "합계", "몇 개", "규모" 류 질의는 숫자·표가 답일 가능성이 높다. entity_key 필터가
# 이미 종목을 좁혀 놓은 상태에서, 표 청크와 산문 청크 중 어느 쪽이 실제로 숫자를 담고
# 있는지까지는 필터가 구분하지 못한다 - 그 구분을 여기서 순위로 보정한다.
_NUMERIC_INTENT_WORDS = ("총", "합계", "몇", "규모", "얼마", "개수", "비중", "집중도")


def wants_numeric_answer(query: str) -> bool:
    return any(word in query for word in _NUMERIC_INTENT_WORDS)


def _bonus(hit: Any, *, entity_key: str | None, period_year: str | None,
          prefer_table: bool, signal: RerankSignal) -> float:
    score = 0.0
    status = getattr(hit, "okf_status", "") or ""
    if status and status != "stable":
        score += signal.status_penalty
    hit_entities = getattr(hit, "entity_key", "") or ""
    if entity_key and hit_entities and entity_key in hit_entities.split("|"):
        score += signal.entity_match
    hit_period = getattr(hit, "period_year", "") or ""
    if period_year and hit_period == period_year:
        score += signal.period_match
    if prefer_table and getattr(hit, "kind", "") == "table":
        score += signal.prefer_table
    return score


def rerank(
    hits: list[Any],
    query: str,
    *,
    entity_key: str | None = None,
    period_year: str | None = None,
    signal: RerankSignal = DEFAULT_SIGNAL,
) -> list[Any]:
    """`hits`를 보너스 내림차순으로 안정 정렬한다. 보너스가 같으면 원래 순서를 지킨다.

    `hits`는 `Hit`/`VectorHit`/`FusedHit` 어느 것이든 된다 - okf_status/entity_key/
    period_year/kind가 없는 타입은 `getattr` 기본값(빈 문자열)으로 처리돼 보너스 0이
    되므로, 안전하게 통과할 뿐 순위를 흔들지 않는다.
    """
    prefer_table = wants_numeric_answer(query)
    scored = [
        (-_bonus(h, entity_key=entity_key, period_year=period_year,
                 prefer_table=prefer_table, signal=signal), i, h)
        for i, h in enumerate(hits)
    ]
    scored.sort(key=lambda x: (x[0], x[1]))
    return [h for _, _, h in scored]

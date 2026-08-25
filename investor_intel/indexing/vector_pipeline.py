"""OKF 번들에서 벡터 인덱스를 만든다. 대상 범위를 여기서 정한다.

## 무엇을 벡터로 만들 것인가

본문이 있고 최신인 문서(status=stable)만 만든다. 제외되는 것은 이렇다.

  stub     1,534건   제목만 있고 본문을 아직 못 가져온 것
  corrupt    211건   글자가 깨져서 본문을 믿을 수 없는 것
  superseded  14건   같은 내용의 재제출본이 따로 있는 것

제목만 있는 문서를 벡터로 만들어 봐야 제목 벡터일 뿐이라 뜻으로 찾는 이점이 거의
없고, 글자가 깨진 문서는 오히려 아무 데나 가까운 노이즈 벡터가 된다.

## 4주차 V4 사건과 무엇이 다른가

4주차에 "본문 없는 문서는 쓸모없으니 빼자"고 BM25 색인에서 지웠다가, 접수번호로
찾는 질문의 정답률이 0.993에서 0.340으로 무너졌다. 그 공시들이 대부분 본문 없는
문서였기 때문이다.

이번에는 지우는 것이 아니라 '추가를 안 하는 것'이다. BM25 인덱스는 4,818건 전부를
그대로 갖고 있고, 벡터만 stable 문서에 대해 더 만든다. 합칠 때 RRF는 합집합을
다루므로 벡터가 없는 문서도 BM25 순위를 타고 그대로 후보에 남는다. 원리적으로
정답이 사라질 수 없는 구조다.

그래도 확인은 한다. `coverage_report`가 평가셋의 정답 문서 중 몇 건이 벡터 대상에서
빠졌는지를 질문 유형별로 세어 준다. 원리적으로 안전하다는 말과 실제로 안전했다는
말은 다르고, V4에서 배운 것이 정확히 그것이다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from investor_intel.indexing.config import IndexConfig
from investor_intel.indexing.embedding import Encoder
from investor_intel.indexing.okf_loader import OkfConcept, load_bundle
from investor_intel.indexing.okf_pipeline import _split
from investor_intel.indexing.splitter import Chunk
from investor_intel.indexing.vector_index import VectorBuildStats, VectorIndex

# 이 상태의 문서만 벡터로 만든다.
DEFAULT_EMBED_STATUSES: tuple[str, ...] = ("stable",)


@dataclass
class VectorScope:
    """벡터로 만들 대상을 정하는 규칙."""

    statuses: tuple[str, ...] = DEFAULT_EMBED_STATUSES
    require_body: bool = True
    min_chars: int = 20

    def accepts(self, concept: OkfConcept) -> tuple[bool, str]:
        if concept.status not in self.statuses:
            return False, f"status:{concept.status}"
        if self.require_body and not concept.has_body:
            return False, "no_body"
        if len(concept.body.strip()) < self.min_chars:
            return False, "too_short"
        return True, ""


@dataclass
class ScopeReport:
    accepted_docs: int = 0
    skipped_docs: int = 0
    skipped_reasons: Counter = field(default_factory=Counter)
    covered_doc_ids: set[str] = field(default_factory=set)
    # 원본 문서 id → concept id. 평가셋의 정답이 원본 id로 적혀 있어서 필요하다.
    native_index: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "accepted_docs": self.accepted_docs,
            "skipped_docs": self.skipped_docs,
            "skipped_reasons": dict(self.skipped_reasons),
        }


def _embed_text(concept: OkfConcept, chunk: Chunk) -> str:
    """벡터로 만들 문장을 조립한다.

    조각 본문 앞에 concept의 description을 붙인다. 조각만 떼어놓으면 어느 회사
    이야기인지 모르는 경우가 많아서, 문맥이 없으면 벡터가 엉뚱한 곳에 놓인다.
    사람이 읽는 요약과 검색용 문맥이 같은 필드라서 둘이 어긋날 일도 없다.
    """
    head = concept.description.strip()
    body = chunk.text.strip()
    if head and body:
        return f"{head}\n\n{body}"
    return head or body


def iter_vector_records(
    bundle: Path,
    cfg: IndexConfig,
    scope: VectorScope,
    report: ScopeReport,
) -> Iterable[dict]:
    for c in load_bundle(bundle):
        # 정답을 어느 id로 적어 두었든 이어 붙을 수 있게 둘 다 등록한다.
        for key in (c.content_hash, c.native_id):
            if key:
                report.native_index.setdefault(key, c.concept_id)
        ok, reason = scope.accepts(c)
        if not ok:
            report.skipped_docs += 1
            report.skipped_reasons[reason] += 1
            continue
        report.accepted_docs += 1
        report.covered_doc_ids.add(c.concept_id)

        chunks: list[Chunk] = []
        n = 0
        for heading, text in c.sections:
            got = _split(text, heading, c.concept_id, n, cfg) if cfg.chunking else \
                [Chunk(c.concept_id, n, heading, text, "prose")]
            chunks += got
            n += len(got)

        for ch in chunks:
            yield {
                "embed_text": _embed_text(c, ch),
                "chunk_uid": f"{c.concept_id}#{ch.ord}",
                "doc_id": c.concept_id,
                "ord": ch.ord,
                "title": c.title,
                "source_type": c.source_system,
                "okf_type": c.okf_type,
                "entity_key": ("|" + "|".join(c.entity_keys) + "|") if c.entity_keys else "",
                "period_year": c.period_year,
                "pub_year": c.published[:4],
                "okf_status": c.status,
                "heading": ch.heading_path,
                "n_chars": len(ch.text),
                "raw_text": ch.text,
            }


def build_vector_index(
    bundle: Path,
    db_path: Path,
    cfg: IndexConfig,
    encoder: Encoder,
    scope: VectorScope | None = None,
    *,
    batch_size: int = 256,
) -> tuple[VectorIndex, VectorBuildStats, ScopeReport]:
    scope = scope or VectorScope()
    report = ScopeReport()
    index = VectorIndex(db_path)
    stats = index.build(iter_vector_records(bundle, cfg, scope, report),
                        encoder, batch_size=batch_size)
    stats.docs_skipped = report.skipped_docs
    stats.skipped_by_status = dict(report.skipped_reasons)
    return index, stats, report


def resolve_gold(item: dict, native_index: dict[str, str] | None) -> str:
    """평가셋의 정답 문서를 concept id로 맞춘다.

    평가셋은 원본 문서 id(`gold_doc`)로 정답을 적어 두었는데, 지식 레이어의 파일은
    다른 id를 쓴다. concept의 provenance.native_id가 원본 id라서 그걸로 이어 붙인다.
    이미 `gold_concept`가 적혀 있으면 그대로 쓴다.
    """
    if item.get("gold_concept"):
        return str(item["gold_concept"])
    gold = str(item.get("gold_doc") or "")
    if native_index and gold in native_index:
        return native_index[gold]
    return gold


def coverage_report(
    covered_doc_ids: set[str],
    eval_items: Sequence[dict],
    *,
    native_index: dict[str, str] | None = None,
    axis_key: str = "axis",
) -> dict:
    """평가셋의 정답 문서 중 몇 건이 벡터 대상에서 빠졌는지 질문 유형별로 센다.

    V4에서 배운 것을 그대로 장치로 만든 것이다. 전체 평균만 보면 특정 유형이 통째로
    죽어도 "조금 떨어졌네" 정도로만 보인다. 유형별로 세어야 보인다.
    """
    total = Counter()
    missing = Counter()
    missing_examples: dict[str, list[str]] = {}
    for item in eval_items:
        axis = str(item.get(axis_key) or item.get("source_type") or "unknown")
        gold = resolve_gold(item, native_index)
        if not gold:
            continue
        total[axis] += 1
        if gold not in covered_doc_ids:
            missing[axis] += 1
            missing_examples.setdefault(axis, []).append(str(item.get("qid") or gold))
    return {
        "by_axis": {
            axis: {
                "questions": total[axis],
                "gold_not_embedded": missing.get(axis, 0),
                "ratio": round(missing.get(axis, 0) / total[axis], 3) if total[axis] else 0.0,
                "examples": missing_examples.get(axis, [])[:5],
            }
            for axis in sorted(total)
        },
        "total_questions": sum(total.values()),
        "total_gold_not_embedded": sum(missing.values()),
        "note": ("벡터가 없는 정답 문서는 BM25 쪽에서 그대로 나온다. "
                 "이 표는 '벡터가 도와줄 수 없는 질문이 어느 유형에 몰려 있는가'를 본다."),
    }

#!/usr/bin/env python
"""BM25만 쓸 때와 뜻 검색을 합쳤을 때를 나란히 채점한다.

    uv run python scripts/eval_hybrid.py \
        --bm25 data/index_variants/V7.sqlite3 \
        --vectors data/index_variants/V8.vec.sqlite3 \
        --model multilingual-e5-large \
        --eval eval/queries_manual.json eval/queries.json

무엇을 보는가.

  recall@10   정답이 상위 10개 안에 들어왔는가
  hit@1       첫 번째가 바로 정답인가
  mrr@10      정답이 몇 등으로 나왔는가

여기에 두 가지를 더 본다.

  rescued     BM25만으로는 못 찾았는데 합치니 찾은 건수
  broken      BM25만으로는 찾았는데 합치니 놓친 건수

`broken`이 있는지를 반드시 확인해야 한다. 평균이 올라도 원래 잘 되던 것이 깨졌다면
그건 개선이 아니다. 4주차에 V4에서 겪은 일이 정확히 그것이었다.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from investor_intel.indexing.bm25_index import Bm25Index
from investor_intel.indexing.embedding import DEFAULT_MODEL, load_encoder
from investor_intel.indexing.hybrid import HybridSearcher
from investor_intel.indexing.okf_loader import load_bundle
from investor_intel.indexing.vector_index import VectorIndex
from investor_intel.indexing.vector_pipeline import resolve_gold


def build_native_index(bundle: Path) -> dict[str, str]:
    idx: dict[str, str] = {}
    for c in load_bundle(bundle):
        for key in (c.content_hash, c.native_id):
            if key:
                idx.setdefault(key, c.concept_id)
    return idx


def rank_of(gold: str, hits) -> int:
    for i, h in enumerate(hits, start=1):
        if h.doc_id == gold:
            return i
    return 0


def score(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {}
    return {
        "n": n,
        "recall@10": round(sum(1 for r in rows if 0 < r["rank"] <= 10) / n, 3),
        "hit@1": round(sum(1 for r in rows if r["rank"] == 1) / n, 3),
        "mrr@10": round(sum(1 / r["rank"] for r in rows if 0 < r["rank"] <= 10) / n, 3),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bm25", type=Path, default=Path("data/index_variants/V7.sqlite3"))
    ap.add_argument("--vectors", type=Path, default=Path("data/index_variants/V8.vec.sqlite3"))
    ap.add_argument("--bundle", type=Path, default=Path("vault/20_Knowledge"))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--eval", type=Path, nargs="+", required=True)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--pool", type=int, default=100)
    ap.add_argument("--vector-weight", type=float, default=1.0)
    ap.add_argument("--min-vector-score", type=float, default=0.0)
    ap.add_argument("--out", type=Path, default=Path("eval/eval_hybrid.json"))
    args = ap.parse_args()

    bm25 = Bm25Index(args.bm25, korean_ngram=True, metadata_boost=True, korean_keep_word=True)
    vectors = VectorIndex(args.vectors)
    encoder = load_encoder(args.model)
    native = build_native_index(args.bundle)

    bm_only = HybridSearcher(bm25, None, None, pool=args.pool)
    hybrid = HybridSearcher(bm25, vectors, encoder, pool=args.pool,
                            vector_weight=args.vector_weight,
                            min_vector_score=args.min_vector_score)

    report: dict = {"model": getattr(encoder, "name", "?"), "sets": {}}
    for path in args.eval:
        items = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(items, dict):
            items = items.get("queries", [])
        base_rows, hyb_rows = [], []
        by_axis: dict[str, dict[str, list]] = defaultdict(lambda: {"base": [], "hyb": []})
        rescued, broken = [], []
        source = Counter()

        unanswerable = 0
        for item in items:
            gold = resolve_gold(item, native)
            query = item["query"]
            axis = str(item.get("axis") or item.get("source_type") or "unknown")
            if not gold:
                # 답이 없어야 정답인 질문. 등수로 잴 수 없어서 따로 센다.
                # 제대로 채점하려면 "근거가 약하면 모른다고 답한다"는 기준선이 필요하고,
                # 그건 답변 생성 단계를 붙인 다음에 할 일이다.
                unanswerable += 1
                continue
            b = rank_of(gold, bm_only.search(query, k=args.k))
            fused = hybrid.search(query, k=args.k)
            h = rank_of(gold, fused)
            base_rows.append({"rank": b})
            hyb_rows.append({"rank": h})
            by_axis[axis]["base"].append({"rank": b})
            by_axis[axis]["hyb"].append({"rank": h})
            if b == 0 and h > 0:
                hit = next((x for x in fused if x.doc_id == gold), None)
                rescued.append({"qid": item.get("qid"), "query": query, "rank": h,
                                "found_by": list(hit.found_by) if hit else []})
                if hit:
                    source[",".join(hit.found_by)] += 1
            if b > 0 and h == 0:
                broken.append({"qid": item.get("qid"), "query": query, "bm25_rank": b})

        report["sets"][path.stem] = {
            "bm25_only": score(base_rows),
            "hybrid": score(hyb_rows),
            "rescued": rescued,
            "broken": broken,
            "rescued_found_by": dict(source),
            "unanswerable_skipped": unanswerable,
            "by_axis": {
                axis: {"bm25_only": score(v["base"]), "hybrid": score(v["hyb"])}
                for axis, v in sorted(by_axis.items())
            },
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for name, res in report["sets"].items():
        b, h = res["bm25_only"], res["hybrid"]
        print(f"\n[{name}] {b.get('n')}건")
        print(f"  recall@10  {b.get('recall@10')} -> {h.get('recall@10')}")
        print(f"  hit@1      {b.get('hit@1')} -> {h.get('hit@1')}")
        print(f"  mrr@10     {b.get('mrr@10')} -> {h.get('mrr@10')}")
        print(f"  새로 찾음 {len(res['rescued'])}건 / 깨짐 {len(res['broken'])}건")
        for row in res["broken"][:5]:
            print(f"    깨짐: {row['qid']} (BM25 {row['bm25_rank']}등이었음) {row['query'][:40]}")


if __name__ == "__main__":
    main()

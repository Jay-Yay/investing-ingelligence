#!/usr/bin/env python
"""OKF 인덱스(V7, `investor-intel index build`가 만드는 것)를 평가셋으로 채점한다.

`scripts/eval_retrieval.py`는 V0~V6(10_Sources 직접 색인) 변형만 다루고, 정답을
원본 문서 id(`gold_doc`) 그대로 쓴다. V7은 색인 입력이 OKF 번들이라 `doc_id`가
concept id로 바뀌어 있다 - `chunk_meta.native_doc_id`(원본 vault 문서 id)로 되짚어야
정답과 맞춰볼 수 있다. 이 스크립트가 그 매핑을 한다.

    uv run python scripts/eval_okf_retrieval.py \
        --search-db data/search_index.sqlite3 --queries eval/manual_queries.json

CI 게이트로 쓸 때는 임계값을 준다 - 미달이면 종료 코드 1이다:

    uv run python scripts/eval_okf_retrieval.py --gate --min-recall10 0.9 --min-hit1 0.6
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from investor_intel.indexing.bm25_index import Bm25Index
from investor_intel.indexing.retrieval import AdaptiveRetriever, EntityLexicon


def native_id_map(index: Bm25Index) -> dict[str, str]:
    """원본 vault 문서 id -> 이 인덱스의 doc_id(concept id)."""
    return {
        str(row["native_doc_id"]): str(row["doc_id"])
        for row in index.conn.execute(
            "SELECT DISTINCT doc_id, native_doc_id FROM chunk_meta WHERE native_doc_id != ''"
        )
    }


def resolve_gold(gold_doc: str, mapping: dict[str, str]) -> str:
    return mapping.get(gold_doc, gold_doc)


def score(index: Bm25Index, retriever: AdaptiveRetriever, queries: list[dict],
         k: int = 10) -> dict:
    """`Router`/`DocumentSearchTool`이 실제로 쓰는 것과 같은 경로(AdaptiveRetriever)로
    채점한다. 원본 BM25 점수만 재면 메타데이터 필터·재랭킹·완화 루프의 효과가 전혀
    반영되지 않아, 실제 서비스 품질과 다른 숫자가 게이트에 올라간다.
    """
    mapping = native_id_map(index)
    unmapped = sum(1 for q in queries if q["gold_doc"] not in mapping)

    hit1 = hit10 = 0
    reciprocal_ranks: list[float] = []
    per_source: dict[str, dict] = {}
    misses: list[dict] = []

    for q in queries:
        gold = resolve_gold(q["gold_doc"], mapping)
        hits = retriever.search(q["query"], k=k).hits
        ids = [h.doc_id for h in hits]
        rank = ids.index(gold) + 1 if gold in ids else 0
        reciprocal_ranks.append(1 / rank if rank else 0.0)
        hit1 += rank == 1
        hit10 += rank > 0
        if not rank:
            misses.append(q)
        bucket = per_source.setdefault(q["source_type"], {"n": 0, "hit10": 0})
        bucket["n"] += 1
        bucket["hit10"] += rank > 0

    n = len(queries)
    return {
        "n": n,
        "unmapped_gold": unmapped,
        "recall@10": round(hit10 / n, 4) if n else 0.0,
        "hit@1": round(hit1 / n, 4) if n else 0.0,
        "mrr@10": round(statistics.mean(reciprocal_ranks), 4) if n else 0.0,
        "by_source_type": {
            src: {"n": b["n"], "recall@10": round(b["hit10"] / b["n"], 4)}
            for src, b in sorted(per_source.items())
        },
        "misses": [{"qid": q["qid"], "query": q["query"]} for q in misses],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--search-db", type=Path, default=Path("data/search_index.sqlite3"))
    ap.add_argument("--bundle", type=Path, default=Path("vault/20_Knowledge"),
                    help="entity_key 필터에 쓸 종목 사전. 없으면 필터 없이 채점한다")
    ap.add_argument("--queries", type=Path, default=Path("eval/manual_queries.json"))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--gate", action="store_true",
                    help="임계값 미달 시 종료 코드 1을 낸다 (CI에서 쓴다)")
    ap.add_argument("--min-recall10", type=float, default=0.0)
    ap.add_argument("--min-hit1", type=float, default=0.0)
    args = ap.parse_args()

    if not args.search_db.exists():
        print(f"검색 인덱스가 없다: {args.search_db} - 먼저 `index build`를 실행하라")
        raise SystemExit(1)

    queries = json.loads(args.queries.read_text(encoding="utf-8"))
    index = Bm25Index(args.search_db, korean_ngram=True, metadata_boost=True,
                      korean_keep_word=True)
    try:
        # EntityLexicon(bundle)은 bundle/companies가 없어도 예외 없이 빈 사전이 된다 -
        # 번들 경로를 안 줘도 필터 없는 채점으로 조용히 내려간다.
        retriever = AdaptiveRetriever(index, EntityLexicon(args.bundle))
        result = score(index, retriever, queries, k=args.k)
    finally:
        index.close()

    print(f"질의 {result['n']}건 (정답 매핑 실패 {result['unmapped_gold']}건)")
    print(f"  recall@{args.k} {result['recall@10']:.3f} · hit@1 {result['hit@1']:.3f} "
          f"· mrr@{args.k} {result['mrr@10']:.3f}")
    for src, stats in result["by_source_type"].items():
        print(f"    {src:<15}{stats['n']:>3}건  recall@{args.k} {stats['recall@10']:.3f}")
    if result["misses"]:
        print(f"  실패한 질의 {len(result['misses'])}건:")
        for miss in result["misses"][:10]:
            print(f"    - [{miss['qid']}] {miss['query']}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.gate:
        failures = []
        if result["recall@10"] < args.min_recall10:
            failures.append(
                f"recall@10 {result['recall@10']:.3f} < 허용 {args.min_recall10:.3f}")
        if result["hit@1"] < args.min_hit1:
            failures.append(f"hit@1 {result['hit@1']:.3f} < 허용 {args.min_hit1:.3f}")
        if failures:
            print("\n[FAIL] 검색 품질이 기준 밑으로 떨어졌다:")
            for f in failures:
                print(f"  - {f}")
            raise SystemExit(1)


if __name__ == "__main__":
    main()

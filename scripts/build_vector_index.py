#!/usr/bin/env python
"""OKF 번들에서 벡터 인덱스를 만든다.

모델을 처음 받을 때만 시간이 걸리고, 그다음부터는 로컬 캐시를 쓴다.

    # 준비 (한 번만)
    uv pip install sentence-transformers

    # 만들기
    uv run python scripts/build_vector_index.py \
        --bundle vault/20_Knowledge \
        --db data/index_variants/V8.vec.sqlite3 \
        --model multilingual-e5-large

    # 모델 없이 파이프라인만 확인
    uv run python scripts/build_vector_index.py --model hash

이미 색인된 청크 저장소(BM25 인덱스)를 입력으로 쓰면 청킹을 두 번 하지 않고, `chunk_uid`가
어긋날 여지도 없어진다(RRF로 두 결과를 합칠 때 그게 문제가 된다).

    uv run python scripts/build_vector_index.py \
        --from-chunk-store data/search_index.sqlite3 \
        --cache data/embedding_cache.sqlite3

`--cache`를 주면 조각 본문 해시로 임베딩을 재사용한다. 바뀐 조각만 실제로 인코딩되므로,
문서 몇 건이 늘었을 때 4만여 조각을 전부 다시 인코딩하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from investor_intel.indexing.config import V7
from investor_intel.indexing.embed_cache import CachedEncoder, EmbeddingCache
from investor_intel.indexing.embedding import DEFAULT_MODEL, MODEL_PRESETS, load_encoder
from investor_intel.indexing.vector_pipeline import (
    VectorScope,
    build_vector_index,
    build_vector_index_from_chunk_store,
    coverage_report,
)


def main() -> None:
    ap = argparse.ArgumentParser(description="OKF 번들 → 벡터 인덱스")
    ap.add_argument("--bundle", type=Path, default=Path("vault/20_Knowledge"))
    ap.add_argument("--db", type=Path, default=Path("data/index_variants/V8.vec.sqlite3"))
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"{', '.join(MODEL_PRESETS)}, hash, api:<모델명>")
    ap.add_argument("--device", default=None, help="cuda, mps, cpu 중 하나. 비우면 자동")
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--statuses", default="stable",
                    help="쉼표로 구분. 기본은 stable만")
    ap.add_argument("--eval", type=Path, default=None,
                    help="평가셋 json. 주면 유형별 커버리지 표를 같이 낸다")
    ap.add_argument("--out", type=Path, default=Path("eval/vector_build.json"))
    ap.add_argument("--from-chunk-store", type=Path, default=None,
                    help="BM25 인덱스 경로. 주면 번들을 다시 청킹하지 않고 그 청크를 쓴다")
    ap.add_argument("--cache", type=Path, default=None,
                    help="임베딩 캐시 경로. 주면 내용이 같은 조각은 다시 인코딩하지 않는다")
    args = ap.parse_args()

    scope = VectorScope(statuses=tuple(s.strip() for s in args.statuses.split(",") if s.strip()))
    kwargs = {}
    if args.device and not args.model.startswith(("hash", "api:")):
        kwargs["device"] = args.device
    encoder = load_encoder(args.model, **kwargs)
    cache = EmbeddingCache(args.cache) if args.cache else None
    if cache is not None:
        encoder = CachedEncoder(encoder, cache)

    args.db.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if args.from_chunk_store:
        index, stats, report = build_vector_index_from_chunk_store(
            args.from_chunk_store, args.db, encoder, scope, batch_size=args.batch_size)
    else:
        index, stats, report = build_vector_index(
            args.bundle, args.db, V7, encoder, scope, batch_size=args.batch_size)
    elapsed = time.time() - t0

    payload = {
        "model": stats.model,
        "dim": stats.dim,
        "chunks_embedded": stats.chunks_embedded,
        "docs_embedded": stats.docs_embedded,
        "scope": report.as_dict(),
        "seconds": round(elapsed, 1),
        "megabytes": round(stats.bytes_on_disk / 1_048_576, 1),
        "source": "chunk_store" if args.from_chunk_store else "bundle",
    }
    if cache is not None:
        payload["cache"] = {
            "hits": cache.stats.hits, "misses": cache.stats.misses,
            "hit_ratio": cache.stats.hit_ratio, "entries": cache.size(stats.model),
        }

    if args.eval and args.eval.exists():
        items = json.loads(args.eval.read_text(encoding="utf-8"))
        if isinstance(items, dict):
            items = items.get("queries", [])
        payload["coverage"] = coverage_report(
            report.covered_doc_ids, items, native_index=report.native_index)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    index.close()
    if cache is not None:
        cache.close()


if __name__ == "__main__":
    main()

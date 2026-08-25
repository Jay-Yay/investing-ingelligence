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
    uv run python scripts/build_vector_index.py --model hash --limit 200
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from investor_intel.indexing.config import V7
from investor_intel.indexing.embedding import DEFAULT_MODEL, MODEL_PRESETS, load_encoder
from investor_intel.indexing.vector_pipeline import (
    VectorScope, build_vector_index, coverage_report)


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
    args = ap.parse_args()

    scope = VectorScope(statuses=tuple(s.strip() for s in args.statuses.split(",") if s.strip()))
    kwargs = {}
    if args.device and not args.model.startswith(("hash", "api:")):
        kwargs["device"] = args.device
    encoder = load_encoder(args.model, **kwargs)

    args.db.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
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


if __name__ == "__main__":
    main()

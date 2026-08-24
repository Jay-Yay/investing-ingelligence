#!/usr/bin/env python
"""만들어진 인덱스에 질의해 본다.

    uv run python scripts/search_vault.py "삼성전자 반도체 설비투자" --k 5
"""
from __future__ import annotations

import argparse
from pathlib import Path

from investor_intel.indexing.bm25_index import Bm25Index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--db", type=Path, default=Path("data/search_index.sqlite3"))
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--chunk-level", action="store_true",
                    help="문서 단위로 묶지 않고 청크를 그대로 반환")
    args = ap.parse_args()

    idx = Bm25Index(args.db, korean_ngram=True, metadata_boost=True, korean_keep_word=True)
    hits = (idx.search(args.query, k=args.k) if args.chunk_level
            else idx.search_documents(args.query, k=args.k))
    for i, h in enumerate(hits, 1):
        head = f"{h.source_type} · {h.title or '(제목 없음)'}"
        if h.heading_path:
            head += f" · {h.heading_path}"
        print(f"\n[{i}] score={h.score:.2f}  {head}")
        print(f"    {h.chunk_uid}  ({h.capture_mode})")
        print("    " + h.text[:300].replace("\n", "\n    "))
    idx.close()


if __name__ == "__main__":
    main()

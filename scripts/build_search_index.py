#!/usr/bin/env python
"""vault를 검색 가능한 청크 인덱스로 만든다.

    uv run python scripts/build_search_index.py --vault vault --db data/search_index.sqlite3
    uv run python scripts/build_search_index.py --variant V0   # 비교용 옛 구성으로 빌드

기존 `data/index.sqlite3`(수집 상태·중복제거용 메타 카탈로그)와는 다른 파일을 쓴다.
둘은 역할이 다르고, 검색 인덱스는 vault만 있으면 언제든 다시 만들 수 있다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from investor_intel.indexing.config import VARIANTS
from investor_intel.indexing.pipeline import build_index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", type=Path, default=Path("vault"))
    ap.add_argument("--db", type=Path, default=Path("data/search_index.sqlite3"))
    ap.add_argument("--variant", default="V6", choices=[c.name for c in VARIANTS])
    ap.add_argument("--stats-json", type=Path, default=None)
    args = ap.parse_args()

    cfg = next(c for c in VARIANTS if c.name == args.variant)
    if args.db.exists():
        args.db.unlink()
    index, stats, telemetry = build_index(args.vault, args.db, cfg)
    index.close()
    telemetry.pop("chunk_chars", None)

    print(f"[{cfg.name}] {cfg.label}")
    print(f"  문서 {stats.n_docs:,} / 청크 {stats.n_chunks:,} / 색인 {stats.n_chars_indexed:,}자")
    print(f"  소요 {stats.build_seconds}s / DB {stats.db_bytes / 1e6:.1f}MB -> {args.db}")
    print(f"  본문 없는 문서 {telemetry['docs_without_body']:,} / "
          f"중복 id 스킵 {telemetry['duplicate_doc_ids_skipped']:,} / "
          f"보일러플레이트 제거 {telemetry['boilerplate_chars_dropped']:,}자")
    if args.stats_json:
        args.stats_json.write_text(
            json.dumps({"variant": cfg.name, "stats": stats.__dict__, "telemetry": telemetry},
                       ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

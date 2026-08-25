#!/usr/bin/env python
"""OKF 번들에서 표 데이터(13F 보유 현황, 공시 카탈로그)를 SQL 인덱스로 만든다.

    uv run python scripts/build_structured_index.py

4주차 자료가 말한 '매출·건수·상태 등 표 데이터 -> SQL Database, Text-to-SQL' 인덱스다.
문서 검색 인덱스와 별개로 존재해야 하며, "몇 개냐" 같은 질문은 이쪽이 답한다.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from investor_intel.indexing.structured import build_structured_index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path, default=Path("vault/20_Knowledge"))
    ap.add_argument("--db", type=Path, default=Path("data/structured.sqlite3"))
    args = ap.parse_args()
    s = build_structured_index(args.bundle, args.db)
    print(f"13F 스냅샷 {s['holdings_snapshots']:,}건 · 보유 행 {s['holding_rows']:,}개")
    print(f"  그중 본문 표가 잘린 스냅샷 {s['truncated_snapshots']:,}건 "
          f"({s['truncated_snapshots'] / max(1, s['holdings_snapshots']):.0%})")
    print(f"공시 카탈로그 {s['filings']:,}건")
    print(f"-> {args.db} ({s['db_bytes'] / 1e6:.1f}MB)")


if __name__ == "__main__":
    main()

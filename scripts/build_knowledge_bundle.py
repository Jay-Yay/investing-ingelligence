#!/usr/bin/env python
"""vault/10_Sources 원본에서 OKF 지식 레이어(vault/20_Knowledge)를 만든다.

    uv run python scripts/build_knowledge_bundle.py --vault vault --out vault/20_Knowledge
    uv run python scripts/build_knowledge_bundle.py --validate-only

원본은 건드리지 않는다. 번들은 언제든 원본에서 다시 만들 수 있는 파생물이다.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from investor_intel.knowledge.builder import build_bundle
from investor_intel.knowledge.validate import validate_bundle


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", type=Path, default=Path("vault"))
    ap.add_argument("--db", type=Path, default=Path("data/index.sqlite3"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--stats-json", type=Path, default=None)
    args = ap.parse_args()
    out = args.out or (args.vault / "20_Knowledge")

    if not args.validate_only:
        if out.exists():
            shutil.rmtree(out)
        stats = build_bundle(args.vault, args.db, out)
        print(f"concept {stats['written']:,}건 -> {out}")
        print(f"  타입: {stats['by_type']}")
        print(f"  status: {stats['status']}")
        print(f"  본문에서 복원한 종목 관계 {stats['mentions_recovered']:,}건 "
              f"(분석 주체로 분리 {stats['analyst_houses_split']:,}건)")
        print(f"  인코딩 손상 {stats['corrupt']:,}건 · 재제출로 대체된 문서 {stats['superseded']:,}건 "
              f"· 중복 id {stats['duplicate_doc_ids_skipped']}건 스킵")
        if args.stats_json:
            args.stats_json.write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                                       encoding="utf-8")

    v = validate_bundle(out)
    print(f"\n검증: 파일 {v['files']:,} · 링크 {v['links_total']:,} "
          f"(깨진 링크 {v['links_broken']}) · 필수 필드 위반 {v['required_field_violations']}")
    if v["dirs_without_index"]:
        print(f"  index.md 없는 디렉터리: {v['dirs_without_index']}")
    for i in v["issues_sample"]:
        print(f"  - {i}")
    print("  OK" if v["ok"] else "  FAILED")
    raise SystemExit(0 if v["ok"] else 1)


if __name__ == "__main__":
    main()

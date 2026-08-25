#!/usr/bin/env python
"""질문 하나를 라우터에 넣어 어떤 도구가 어떻게 답하는지 본다.

    uv run python scripts/ask.py "베일리기포드 2025년 4분기 13F 편입 종목 개수"
    uv run python scripts/ask.py "삼성전자 2010년 1분기 분기보고서 접수번호"
    uv run python scripts/ask.py "하워드 막스가 신용 사고를 어떤 전조로 봤나"

4주차 자료의 "질문 성격에 맞는 데이터 소스와 도구를 선택해야 한다"를 눈으로 확인하는 용도다.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from investor_intel.indexing.router import Router


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--bundle", type=Path, default=Path("vault/20_Knowledge"))
    ap.add_argument("--chunk-db", type=Path, default=Path("data/search_index.sqlite3"))
    ap.add_argument("--structured-db", type=Path, default=Path("data/structured.sqlite3"))
    args = ap.parse_args()

    router = Router(args.bundle, args.chunk_db, args.structured_db)
    print("등록된 도구")
    for t in router.tools():
        print(f"  - {t.name}: {t.description}")

    out = router.answer(args.query)
    print(f"\n질문: {args.query}")
    for i, step in enumerate(out.trace, 1):
        print(f"  {i}. [{step.step}] {step.detail}")
    print(f"\n고른 도구: {out.tool}")
    if out.result.answer:
        print(f"답: {out.result.answer}")
    if out.result.note:
        print(f"주의: {out.result.note}")
    for i, e in enumerate(out.result.evidence[:5], 1):
        label = e.get("title") or e.get("investor") or e.get("concept_id", "")
        print(f"  근거 {i}. {str(label)[:80]}")


if __name__ == "__main__":
    main()

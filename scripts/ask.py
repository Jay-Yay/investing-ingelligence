#!/usr/bin/env python
"""질문 하나를 라우터에 넣어 어떤 도구가 어떻게 답하는지 본다.

    uv run python scripts/ask.py "베일리기포드 2025년 4분기 13F 편입 종목 개수"
    uv run python scripts/ask.py "삼성전자 2010년 1분기 분기보고서 접수번호"
    uv run python scripts/ask.py "하워드 막스가 신용 사고를 어떤 전조로 봤나"
    uv run python scripts/ask.py "에이피알을 다룬 채널이 또 무엇을 언급했나"

Hybrid Search를 켜려면 벡터 인덱스 경로를 함께 준다(먼저 build_vector_index.py로
만들어 둬야 한다):

    uv run python scripts/ask.py "..." --vector-db data/vector_index.sqlite3

4주차 자료의 "질문 성격에 맞는 데이터 소스와 도구를 선택해야 한다"를 눈으로 확인하는 용도다.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from investor_intel.indexing.answer import build_answer_bundle
from investor_intel.indexing.router import Router

if TYPE_CHECKING:
    from investor_intel.indexing.embedding import Encoder
    from investor_intel.indexing.vector_index import VectorIndex


def _load_vector_backend(
    vector_db: Path | None, embed_model: str | None
) -> tuple[VectorIndex | None, Encoder | None]:
    """Router는 스스로 임베딩 모델을 로딩하지 않는다 - 그 책임은 여기, CLI 쪽에 있다."""
    if vector_db is None or not vector_db.exists():
        return None, None
    import json

    from investor_intel.indexing.embedding import load_encoder
    from investor_intel.indexing.vector_index import VectorIndex

    index = VectorIndex(vector_db)
    model = embed_model
    if model is None:
        row = index.conn.execute("SELECT value FROM vec_info WHERE key = 'build'").fetchone()
        if row:
            model = json.loads(row[0]).get("model")
    if not model:
        print(f"[경고] {vector_db}에서 임베딩 모델 이름을 알아내지 못해 벡터 검색을 끈다.")
        return None, None
    return index, load_encoder(model)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--bundle", type=Path, default=Path("vault/20_Knowledge"))
    ap.add_argument("--chunk-db", type=Path, default=Path("data/search_index.sqlite3"))
    ap.add_argument("--structured-db", type=Path, default=Path("data/structured.sqlite3"))
    ap.add_argument("--vector-db", type=Path, default=None,
                    help="주면 Hybrid Search(BM25 + 벡터)로 동작한다")
    ap.add_argument("--embed-model", default=None,
                    help="비우면 --vector-db에 기록된 모델을 그대로 쓴다")
    args = ap.parse_args()

    vector_index, encoder = _load_vector_backend(args.vector_db, args.embed_model)
    router = Router(args.bundle, args.chunk_db, args.structured_db,
                    vector_index=vector_index, encoder=encoder)
    print("등록된 도구" + (" (Hybrid Search 켜짐)" if router.docs.retriever.vector_enabled else ""))
    for t in router.tools():
        print(f"  - {t.name}: {t.description}")

    out = router.answer(args.query)
    print(f"\n질문: {args.query}")
    for i, step in enumerate(out.trace, 1):
        print(f"  {i}. [{step.step}] {step.detail}")
    print(f"\n고른 도구: {out.tool}")

    bundle = build_answer_bundle(args.query, out)
    print(f"\n{bundle.render()}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""검색 품질 평가 하네스.

    uv run python scripts/eval_retrieval.py gen   --vault vault --out eval/queries.json
    uv run python scripts/eval_retrieval.py score --vault vault --queries eval/queries.json

`gen`은 코퍼스에서 평가 질의를 결정론적으로(고정 seed) 생성한다. 네 계열이다.

  A1 구절_원형    문서 뒷부분에서 뽑은 내용어를 그대로 질의로 씀
  A2 구절_기본형  같은 구절에서 조사를 떼고 질의로 씀 (사용자가 실제로 입력하는 형태)
  B  형태변형     특정 문서에만 '부분 문자열'로 존재하고 어절로는 없는 한글 표현
  C  식별자       accession number, 문서 제목

`score`는 변형별 인덱스를 돌며 doc 단위 recall@10 / hit@k / MRR과, 정답 1건을 얻기 위해
LLM에 넣게 되는 컨텍스트 글자수(top-5 반환 텍스트 합)를 잰다.

주의: 자동 생성 질의는 정답 구절과 어휘를 공유하므로 절대 수치는 낙관적이다. 의미가 있는
것은 변형 간 '상대 비교'다. 사람이 다시 쓴 질의(어휘가 겹치지 않는 질문)로는 결과가
크게 달라지므로, 자동셋만으로 결론을 내면 안 된다 — docs/indexing_experiment.md 참고.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from investor_intel.indexing.bm25_index import Bm25Index
from investor_intel.indexing.config import VARIANTS
from investor_intel.indexing.loader import load_vault

SEED = 20260824

_JOSA = ("에서는", "으로서", "이라고", "까지도", "에게서", "으로써", "라고는", "에서도", "이라는",
         "으로", "에서", "에게", "까지", "부터", "이라", "라는", "보다", "처럼", "마다", "조차",
         "이나", "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "만", "로")
_STOP = set("그리고 그러나 하지만 또한 그런데 이는 있다 없다 한다 했다 됐다 된다 대한 위한 통해 "
            "따라 대해 관련 이번 지난 오는 있는 없는 하는 되는 및 등 수 것 때 년 월 일".split())


def _strip_josa(word: str) -> str:
    if not re.fullmatch(r"[가-힣]+", word) or len(word) < 3:
        return word
    for j in sorted(_JOSA, key=len, reverse=True):
        if word.endswith(j) and len(word) - len(j) >= 2:
            return word[: -len(j)]
    return word


def _content_words(text: str) -> list[str]:
    ws = re.findall(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9\-]{2,}|\d[\d,.]{2,}", text)
    return [w for w in ws if w not in _STOP]


def _unique_docs(vault: Path):
    seen: set[str] = set()
    out = []
    for d in load_vault(vault, strip_boilerplate=True):
        if d.doc_id in seen:
            continue
        seen.add(d.doc_id)
        out.append(d)
    return out


def generate(vault: Path, out_path: Path) -> None:
    random.seed(SEED)
    docs = _unique_docs(vault)
    with_body = [d for d in docs if d.has_body and len(d.body) > 600]
    queries: list[dict] = []

    pool: dict[str, list] = defaultdict(list)
    for d in with_body:
        pool[d.source_type].append(d)
    sample = []
    for st, n in {"telegram": 45, "dart": 45, "naver": 40, "ib_insights": 40,
                  "sec_filing": 15, "sec_13f": 15}.items():
        sample += random.sample(pool.get(st, []), min(n, len(pool.get(st, []))))

    for i, d in enumerate(sample):
        body = d.body
        lo = int(len(body) * 0.5)  # 뒷부분에서 뽑는다 - 긴 문서의 뒤가 실제로 닿는지가 관건
        start = random.randint(lo, max(lo, len(body) - 400))
        words = _content_words(body[start : start + 350])
        if len(words) < 6:
            continue
        pick = words[:14]
        random.shuffle(pick)
        pick = pick[:9]
        base = {"gold_doc": d.doc_id, "source_type": d.source_type, "doc_chars": len(body),
                "span_offset_ratio": round(start / max(1, len(body)), 3)}
        queries.append({"qid": f"A1-{i:03d}", "family": "A1_구절_원형",
                        "query": " ".join(pick), **base})
        queries.append({"qid": f"A2-{i:03d}", "family": "A2_구절_기본형",
                        "query": " ".join(dict.fromkeys(_strip_josa(w) for w in pick)), **base})

    word_sets = {d.doc_id: set(re.findall(r"[가-힣]+", d.body)) for d in with_body}
    term_docs: dict[str, set[str]] = defaultdict(set)
    for d in with_body:
        for w in set(re.findall(r"[가-힣]{5,10}", d.body)):
            for length in (4, 5):
                if len(w) > length:
                    term_docs[w[:length]].add(d.doc_id)
    cands = [(t, next(iter(s))) for t, s in term_docs.items()
             if len(s) == 1 and t not in word_sets[next(iter(s))]]
    random.shuffle(cands)
    for i, (term, did) in enumerate(cands[:100]):
        queries.append({"qid": f"B-{i:03d}", "family": "B_한국어_형태변형", "query": term,
                        "gold_doc": did, "source_type": "", "doc_chars": 0,
                        "span_offset_ratio": None})

    accs = [(d.doc_id, str(d.accession_number)) for d in docs if d.accession_number]
    random.shuffle(accs)
    for i, (did, acc) in enumerate(accs[:80]):
        queries.append({"qid": f"C-{i:03d}", "family": "C_식별자", "query": acc, "gold_doc": did,
                        "source_type": "", "doc_chars": 0, "span_offset_ratio": None})
    titled = [d for d in docs if d.title and len(d.title) > 12]
    random.shuffle(titled)
    for i, d in enumerate(titled[:70]):
        queries.append({"qid": f"C-T{i:03d}", "family": "C_식별자", "query": d.title[:60],
                        "gold_doc": d.doc_id, "source_type": d.source_type,
                        "doc_chars": len(d.body), "span_offset_ratio": None})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"seed": SEED, "n": len(queries), "queries": queries},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"질의 {len(queries)}건 -> {out_path}  {dict(Counter(q['family'] for q in queries))}")


def _measure(cfg, index_dir: Path, queries: list[dict], doc_agg: bool) -> dict:
    idx = Bm25Index(index_dir / f"{cfg.name}.sqlite3", korean_ngram=cfg.korean_ngram,
                    metadata_boost=cfg.metadata_boost, korean_keep_word=cfg.korean_keep_word)
    hit1 = hit5 = hit10 = 0
    rr: list[float] = []
    ctx: list[int] = []
    ms: list[float] = []
    for q in queries:
        t0 = time.perf_counter()
        hits = (idx.search_documents(q["query"], k=10,
                                     exclude_metadata_only=cfg.separate_metadata_only)
                if doc_agg else
                idx.search(q["query"], k=10, exclude_metadata_only=cfg.separate_metadata_only))
        ms.append((time.perf_counter() - t0) * 1000)
        ids = [h.doc_id for h in hits]
        rank = ids.index(q["gold_doc"]) + 1 if q["gold_doc"] in ids else 0
        rr.append(1 / rank if rank else 0.0)
        hit1 += rank == 1
        hit5 += 0 < rank <= 5
        hit10 += rank > 0
        ctx.append(sum(len(h.text) for h in hits[:5]))
    idx.close()
    n = len(queries)
    return {"n": n, "recall@10": round(hit10 / n, 4), "hit@5": round(hit5 / n, 4),
            "hit@1": round(hit1 / n, 4), "mrr@10": round(statistics.mean(rr), 4),
            "ctx5_median": int(statistics.median(ctx)),
            "ms_median": round(statistics.median(ms), 1)}


def score(queries_path: Path, index_dir: Path, out_path: Path | None) -> None:
    queries = json.loads(queries_path.read_text(encoding="utf-8"))["queries"]
    families = sorted({q["family"] for q in queries})
    results: dict[str, dict] = {}
    print(f'{"변형":<5}{"설명":<32}{"recall@10":>10}{"mrr@10":>9}{"hit@1":>8}{"ctx5":>9}')
    for cfg in VARIANTS:
        if not (index_dir / f"{cfg.name}.sqlite3").exists():
            continue
        overall = _measure(cfg, index_dir, queries, doc_agg=False)
        results[cfg.name] = {"label": cfg.label, "ALL": overall,
                             **{f: _measure(cfg, index_dir, [q for q in queries if q["family"] == f],
                                            doc_agg=False) for f in families}}
        print(f'{cfg.name:<5}{cfg.label:<32}{overall["recall@10"]:>10.3f}'
              f'{overall["mrr@10"]:>9.3f}{overall["hit@1"]:>8.3f}{overall["ctx5_median"]:>9,}')
    final = next(c for c in VARIANTS if c.name == "V6")
    if (index_dir / "V6.sqlite3").exists():
        agg = _measure(final, index_dir, queries, doc_agg=True)
        results["V6+docagg"] = {"label": "V6 + 문서집계(max)", "ALL": agg}
        print(f'{"V6+":<5}{"+ 문서집계(max)":<32}{agg["recall@10"]:>10.3f}'
              f'{agg["mrr@10"]:>9.3f}{agg["hit@1"]:>8.3f}{agg["ctx5_median"]:>9,}')
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["gen", "score"])
    ap.add_argument("--vault", type=Path, default=Path("vault"))
    ap.add_argument("--queries", type=Path, default=Path("eval/queries.json"))
    ap.add_argument("--index-dir", type=Path, default=Path("data/index_variants"))
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    if args.command == "gen":
        generate(args.vault, args.out or args.queries)
    else:
        score(args.queries, args.index_dir, args.out)


if __name__ == "__main__":
    main()

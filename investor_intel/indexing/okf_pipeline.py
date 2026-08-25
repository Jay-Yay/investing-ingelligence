from __future__ import annotations

from pathlib import Path

from investor_intel.indexing.bm25_index import Bm25Index, IndexStats
from investor_intel.indexing.config import IndexConfig
from investor_intel.indexing.okf_loader import load_bundle
from investor_intel.indexing.splitter import Chunk, _blocks, _split_prose, _split_table


def _split(text: str, heading: str, doc_id: str, start_ord: int, cfg: IndexConfig):
    chunks: list[Chunk] = []
    n = start_ord
    cur = ""
    for kind, block in _blocks(text):
        pieces = (_split_table(block, cfg.max_chars) if kind == "table"
                  else ([block] if len(block) <= cfg.max_chars
                        else _split_prose(block, cfg.max_chars, cfg.overlap_chars)))
        for piece in pieces:
            if kind == "table":
                if cur.strip():
                    chunks.append(Chunk(doc_id, n, heading, cur.strip(), "prose")); n += 1; cur = ""
                chunks.append(Chunk(doc_id, n, heading, piece.strip(), "table")); n += 1
                continue
            if len(cur) + len(piece) + 1 > cfg.target_chars and cur.strip():
                chunks.append(Chunk(doc_id, n, heading, cur.strip(), "prose")); n += 1
                cur = (cur[-cfg.overlap_chars:] + "\n" + piece) if cfg.overlap_chars else piece
            else:
                cur = f"{cur}\n{piece}".strip()
    if cur.strip():
        chunks.append(Chunk(doc_id, n, heading, cur.strip(), "prose")); n += 1
    return chunks


def build_okf_index(bundle: Path, db_path: Path, cfg: IndexConfig) -> tuple[Bm25Index, IndexStats, dict]:
    """OKF 번들을 검색 인덱스로 소비한다(OKF 용어로는 consumer).

    청킹·토크나이징은 10_Sources를 읽는 경로와 완전히 같다. 달라지는 것은 딱 둘이다.
      1) 청크에 붙는 문맥이 concept의 `description`이다 - 사람이 읽는 요약과
         검색용 문맥이 같은 필드가 된다(따로 관리하면 반드시 어긋난다).
      2) entities/period/status가 필터 가능한 컬럼으로 인덱스에 들어간다.
    """
    index = Bm25Index(db_path, korean_ngram=cfg.korean_ngram, metadata_boost=cfg.metadata_boost,
                      korean_keep_word=cfg.korean_keep_word)
    tel = {"concepts": 0, "stubs": 0, "chunks_by_kind": {}, "with_entity": 0,
           "with_period": 0, "chunk_chars": []}

    def records():
        for c in load_bundle(bundle):
            tel["concepts"] += 1
            if not c.has_body:
                tel["stubs"] += 1
            if c.entity_keys:
                tel["with_entity"] += 1
            if c.period_year:
                tel["with_period"] += 1

            chunks: list[Chunk] = []
            n = 0
            for heading, text in c.sections:
                got = _split(text, heading, c.concept_id, n, cfg) if cfg.chunking else \
                    [Chunk(c.concept_id, n, heading, text, "prose")]
                chunks += got
                n += len(got)
            if not chunks:
                # 본문 없는 concept도 메타데이터 레코드로 남긴다. 검색에서 지우지 않는
                # 이유는 accession number 조회 같은 질의의 유일한 정답이기 때문이다.
                chunks = [Chunk(c.concept_id, 0, "", " ".join(
                    filter(None, [c.title, c.subject_name, c.fiscal])).strip() or c.title,
                    "metadata")]

            ctx_base = c.description if cfg.context_header else ""
            for ch in chunks:
                tel["chunks_by_kind"][ch.kind] = tel["chunks_by_kind"].get(ch.kind, 0) + 1
                tel["chunk_chars"].append(len(ch.text))
                ctx = ctx_base
                if ctx and c.tags:
                    ctx = f"{ctx} [{' '.join(c.tags)}]"
                yield (
                    {
                        "chunk_uid": f"{c.concept_id}#{ch.ord}", "doc_id": c.concept_id,
                        "ord": ch.ord, "doc_path": c.path, "source_type": c.source_system,
                        "source_name": c.subject_name, "published_at": c.published,
                        "title": c.title, "filing_type": c.fiscal, "capture_mode": c.capture,
                        "heading_path": ch.heading_path, "kind": ch.kind,
                        "okf_type": c.okf_type,
                        # 다중 엔티티는 |a|b| 형태로 담아 LIKE로도 걸 수 있게 한다
                        "entity_key": ("|" + "|".join(c.entity_keys) + "|") if c.entity_keys else "",
                        "period_year": c.period_year, "pub_year": c.published[:4],
                        "okf_status": c.status,
                        "n_chars": len(ch.text), "raw_text": ch.text,
                    },
                    ctx,
                    c.title if cfg.metadata_boost else "",
                    ch.text,
                )

    stats = index.build(records())
    return index, stats, tel

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from investor_intel.indexing.bm25_index import Bm25Index, IndexStats
from investor_intel.indexing.config import IndexConfig
from investor_intel.indexing.okf_loader import OkfConcept, load_bundle
from investor_intel.indexing.splitter import Chunk, _blocks, _split_prose, _split_table
from investor_intel.indexing.state import BUILDER_VERSION, IndexState, UpdatePlan, fingerprint

Record = tuple[dict, str, str, str]


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


def index_signature(cfg: IndexConfig) -> str:
    """이 인덱스가 어떤 규칙으로 만들어졌는지. 달라지면 증분이 아니라 전량 재구축이다."""
    return f"{cfg.name}/{BUILDER_VERSION}"


def concept_chunks(concept: OkfConcept, cfg: IndexConfig) -> list[Chunk]:
    """concept 하나를 청크로 나눈다. 청킹은 결정론적이므로 같은 입력이면 같은 결과다."""
    chunks: list[Chunk] = []
    n = 0
    for heading, text in concept.sections:
        got = (_split(text, heading, concept.concept_id, n, cfg) if cfg.chunking
               else [Chunk(concept.concept_id, n, heading, text, "prose")])
        chunks += got
        n += len(got)
    if not chunks:
        # 본문 없는 concept도 메타데이터 레코드로 남긴다. 검색에서 지우지 않는
        # 이유는 accession number 조회 같은 질의의 유일한 정답이기 때문이다.
        chunks = [Chunk(concept.concept_id, 0, "", " ".join(
            filter(None, [concept.title, concept.subject_name, concept.fiscal])).strip()
            or concept.title, "metadata")]
    return chunks


def concept_records(concept: OkfConcept, cfg: IndexConfig) -> Iterator[Record]:
    """concept 하나가 만드는 색인 레코드.

    청크에 붙는 문맥은 concept의 `description`이다 - 사람이 읽는 요약과 검색용 문맥이 같은
    필드가 된다(따로 관리하면 반드시 어긋난다). entities/period/status는 필터 가능한
    컬럼으로 들어간다.
    """
    ctx_base = concept.description if cfg.context_header else ""
    for chunk in concept_chunks(concept, cfg):
        ctx = ctx_base
        if ctx and concept.tags:
            ctx = f"{ctx} [{' '.join(concept.tags)}]"
        yield (
            {
                "chunk_uid": f"{concept.concept_id}#{chunk.ord}",
                "doc_id": concept.concept_id,
                "ord": chunk.ord, "doc_path": concept.path,
                "source_type": concept.source_system, "source_name": concept.subject_name,
                "published_at": concept.published, "title": concept.title,
                "filing_type": concept.fiscal, "capture_mode": concept.capture,
                "heading_path": chunk.heading_path, "kind": chunk.kind,
                "okf_type": concept.okf_type,
                # 다중 엔티티는 |a|b| 형태로 담아 LIKE로도 걸 수 있게 한다
                "entity_key": ("|" + "|".join(concept.entity_keys) + "|")
                if concept.entity_keys else "",
                "period_year": concept.period_year, "pub_year": concept.published[:4],
                "okf_status": concept.status,
                "n_chars": len(chunk.text), "raw_text": chunk.text,
                # 문맥을 토큰화 전 원문으로도 저장한다 - 벡터 인덱스가 이 청크를 그대로 쓴다.
                "ctx_text": ctx,
                # provenance.content_hash에는 원본 vault 문서의 id가 들어 있다.
                "native_doc_id": concept.content_hash,
            },
            ctx,
            concept.title if cfg.metadata_boost else "",
            chunk.text,
        )


def _telemetry() -> dict:
    return {"concepts": 0, "stubs": 0, "chunks_by_kind": {}, "with_entity": 0,
            "with_period": 0, "chunk_chars": []}


def _observe(tel: dict, concept: OkfConcept, records: list[Record]) -> None:
    tel["concepts"] += 1
    if not concept.has_body:
        tel["stubs"] += 1
    if concept.entity_keys:
        tel["with_entity"] += 1
    if concept.period_year:
        tel["with_period"] += 1
    for meta, *_ in records:
        tel["chunks_by_kind"][meta["kind"]] = tel["chunks_by_kind"].get(meta["kind"], 0) + 1
        tel["chunk_chars"].append(meta["n_chars"])


def build_okf_index(
    bundle: Path, db_path: Path, cfg: IndexConfig
) -> tuple[Bm25Index, IndexStats, dict]:
    """OKF 번들을 검색 인덱스로 통째로 다시 만든다(OKF 용어로는 consumer).

    청킹·토크나이징은 10_Sources를 읽는 경로와 완전히 같다. 평가용 변형(variant) 비교는
    이 전량 빌드를 쓴다 - 변형마다 인덱스가 따로 있어야 통제된 비교가 된다.
    운영 갱신은 `update_okf_index`를 쓴다.
    """
    index = Bm25Index(db_path, korean_ngram=cfg.korean_ngram, metadata_boost=cfg.metadata_boost,
                      korean_keep_word=cfg.korean_keep_word)
    tel = _telemetry()
    state = IndexState(index.conn)
    state.clear()

    def records() -> Iterable[Record]:
        for concept in load_bundle(bundle):
            got = list(concept_records(concept, cfg))
            _observe(tel, concept, got)
            state.record_indexed(concept.concept_id,
                                 fingerprint(concept.raw_hash, index_signature(cfg)), len(got))
            yield from got

    stats = index.build(records())
    state.set_info("signature", index_signature(cfg))
    index.conn.commit()
    return index, stats, tel


@dataclass
class UpdateStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    chunks_written: int = 0
    chars_written: int = 0
    full_rebuild: bool = False
    rebuild_reason: str = ""
    seconds: float = 0.0
    telemetry: dict = field(default_factory=dict)

    @property
    def touched(self) -> int:
        return self.added + self.updated + self.removed


def update_okf_index(
    bundle: Path, db_path: Path, cfg: IndexConfig
) -> tuple[Bm25Index, UpdateStats]:
    """바뀐 concept만 다시 색인한다.

    `Bm25Index.build()`는 문서 한 건이 늘어도 전량을 다시 청킹·색인한다. 수집이 증분인데
    색인이 전량이면 두 주기가 맞지 않아 결국 색인이 밀린다. 여기서는 concept 파일 해시로
    바뀐 것만 골라 문서 단위로 갈아끼운다.

    인덱스 설정(변형 이름 + 빌더 버전)이 달라졌거나 상태 기록이 없으면 전량 재구축으로
    떨어진다 - 청킹 규칙이 바뀌었는데 옛 색인을 조용히 유지하는 것보다 안전하다.
    """
    t0 = time.time()
    index = Bm25Index(db_path, korean_ngram=cfg.korean_ngram, metadata_boost=cfg.metadata_boost,
                      korean_keep_word=cfg.korean_keep_word)
    state = IndexState(index.conn)
    signature = index_signature(cfg)

    concepts = {c.concept_id: c for c in load_bundle(bundle)}
    present = {cid: fingerprint(c.raw_hash, signature) for cid, c in concepts.items()}
    plan: UpdatePlan = state.plan(present, signature)

    if plan.full_rebuild:
        index.close()
        index, build_stats, tel = build_okf_index(bundle, db_path, cfg)
        return index, UpdateStats(
            added=build_stats.n_docs, chunks_written=build_stats.n_chunks,
            chars_written=build_stats.n_chars_indexed, full_rebuild=True,
            rebuild_reason=plan.rebuild_reason, seconds=round(time.time() - t0, 2),
            telemetry=tel)

    known = state.fingerprints()
    stats = UpdateStats(unchanged=len(plan.unchanged))
    tel = _telemetry()

    for concept_id in sorted(plan.changed):
        concept = concepts[concept_id]
        records = list(concept_records(concept, cfg))
        _observe(tel, concept, records)
        n_chunks, n_chars = index.upsert_document(concept_id, records)
        state.record_indexed(concept_id, plan.changed[concept_id], n_chunks)
        stats.chunks_written += n_chunks
        stats.chars_written += n_chars
        if concept_id in known:
            stats.updated += 1
        else:
            stats.added += 1

    if plan.removed:
        index.delete_documents(plan.removed)
        state.forget(plan.removed)
        stats.removed = len(plan.removed)

    if stats.touched:
        index.optimize()
    index.conn.commit()
    stats.seconds = round(time.time() - t0, 2)
    stats.telemetry = tel
    return index, stats

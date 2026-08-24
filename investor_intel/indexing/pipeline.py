from __future__ import annotations

from pathlib import Path

from investor_intel.indexing.bm25_index import Bm25Index, IndexStats
from investor_intel.indexing.config import IndexConfig
from investor_intel.indexing.loader import load_vault
from investor_intel.indexing.splitter import context_header, split_document


def build_index(vault_path: Path, db_path: Path, cfg: IndexConfig) -> tuple[Bm25Index, IndexStats, dict]:
    """Load -> Split -> Contextualize -> Store 를 한 번에 실행한다."""
    index = Bm25Index(db_path, korean_ngram=cfg.korean_ngram, metadata_boost=cfg.metadata_boost,
                      korean_keep_word=cfg.korean_keep_word)
    telemetry = {"docs": 0, "docs_without_body": 0, "boilerplate_chars_dropped": 0,
                 "duplicate_doc_ids_skipped": 0, "chunks_by_kind": {}, "chunk_chars": []}
    seen_doc_ids: set[str] = set()

    def records():
        for doc in load_vault(vault_path, strip_boilerplate=cfg.strip_boilerplate):
            # vault에는 같은 frontmatter id를 가진 사본이 서로 다른 경로에 존재한다
            # (published_at이 재수집 때 바뀌면 path_for_document가 새 파일을 만든다).
            # 색인 단계에서 한 번 더 걸러야 같은 근거가 검색 결과에 중복으로 뜨지 않는다.
            if doc.doc_id in seen_doc_ids:
                telemetry["duplicate_doc_ids_skipped"] += 1
                continue
            seen_doc_ids.add(doc.doc_id)
            telemetry["docs"] += 1
            telemetry["boilerplate_chars_dropped"] += doc.dropped_boilerplate_chars
            if not doc.has_body:
                telemetry["docs_without_body"] += 1
            chunks = split_document(
                doc, chunking=cfg.chunking, target_chars=cfg.target_chars,
                max_chars=cfg.max_chars, overlap_chars=cfg.overlap_chars,
            )
            for ch in chunks:
                ctx = context_header(doc, ch) if cfg.context_header else ""
                telemetry["chunks_by_kind"][ch.kind] = telemetry["chunks_by_kind"].get(ch.kind, 0) + 1
                telemetry["chunk_chars"].append(len(ch.text))
                yield (
                    {
                        "chunk_uid": f"{doc.doc_id}#{ch.ord}",
                        "doc_id": doc.doc_id, "ord": ch.ord, "doc_path": doc.path,
                        "source_type": doc.source_type, "source_name": doc.source_name,
                        "published_at": doc.published_at, "title": doc.title,
                        "filing_type": doc.filing_type, "capture_mode": doc.capture_mode,
                        "heading_path": ch.heading_path, "kind": ch.kind,
                        "n_chars": len(ch.text), "raw_text": ch.text,
                    },
                    ctx,
                    doc.title if cfg.metadata_boost else "",
                    ch.text,
                )

    stats = index.build(records())
    return index, stats, telemetry

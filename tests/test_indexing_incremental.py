from __future__ import annotations

from pathlib import Path

from investor_intel.indexing.bm25_index import Bm25Index
from investor_intel.indexing.config import V7
from investor_intel.indexing.okf_pipeline import build_okf_index, update_okf_index
from investor_intel.knowledge.schema import Concept, EntityRef, Period, Provenance

# --- 작은 OKF 번들 만들기 ---------------------------------------------------------------


def _write_concept(bundle: Path, key: str, body: str, *, title: str | None = None,
                   native: str = "", doc_id: str = "") -> Path:
    concept = Concept(
        type="MarketCommentary",
        title=title or f"{key} 제목",
        description=f"{key} 요약",
        key=key,
        folder="commentary",
        period=Period(published="2026-07-08"),
        subject=EntityRef("channel", "ch-telegram-test", "테스트 채널"),
        provenance=Provenance(system="telegram", native_id=native, collected_at="",
                              content_hash=doc_id or key, source_path=""),
        body=body,
    )
    path = bundle / "commentary" / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(concept.render(), encoding="utf-8")
    return path


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "20_Knowledge"
    _write_concept(bundle, "doc-a", "에이피알 매출액이 늘었다는 내용입니다.")
    _write_concept(bundle, "doc-b", "코스맥스 해외 매출이 좋다는 내용입니다.")
    return bundle


# --- 청크 저장소 단위 --------------------------------------------------------------------


def _record(doc_id: str, ord_: int, body: str) -> tuple[dict, str, str, str]:
    return (
        {"chunk_uid": f"{doc_id}#{ord_}", "doc_id": doc_id, "ord": ord_, "doc_path": "p",
         "source_type": "telegram", "source_name": "s", "published_at": "2026-07-08",
         "title": "t", "filing_type": None, "capture_mode": "full", "heading_path": "",
         "kind": "prose", "n_chars": len(body), "raw_text": body},
        "문맥", "t", body,
    )


def test_upsert_replaces_a_documents_chunks_without_touching_others(tmp_path: Path) -> None:
    index = Bm25Index(tmp_path / "idx.sqlite3")
    index.build([_record("a", 0, "첫 문서 본문"), _record("b", 0, "둘째 문서 본문")])

    index.upsert_document("a", [_record("a", 0, "갈아끼운 본문"), _record("a", 1, "추가 청크")])
    stats = index.stats()
    assert stats.n_docs == 2
    assert stats.n_chunks == 3
    assert index.search("갈아끼운")
    assert not index.search("첫")            # 옛 청크는 사라졌다
    assert index.search("둘째")              # 다른 문서는 그대로다
    index.close()


def test_delete_leaves_no_orphan_rows_in_the_fts_table(tmp_path: Path) -> None:
    """chunk_meta만 지우면 FTS 쪽에 고아 행이 남아 지운 문서가 계속 검색된다."""
    index = Bm25Index(tmp_path / "idx.sqlite3")
    index.build([_record("a", 0, "지울 문서 본문"), _record("b", 0, "남길 문서 본문")])

    index.delete_documents(["a"])
    meta = index.conn.execute("SELECT COUNT(*) FROM chunk_meta").fetchone()[0]
    fts = index.conn.execute("SELECT COUNT(*) FROM chunk_fts").fetchone()[0]
    assert meta == fts == 1
    assert not index.search("지울")
    index.close()


def test_upsert_of_an_unknown_document_just_inserts(tmp_path: Path) -> None:
    index = Bm25Index(tmp_path / "idx.sqlite3")
    index.build([])
    n_chunks, n_chars = index.upsert_document("new", [_record("new", 0, "새 문서")])
    assert n_chunks == 1 and n_chars == len("새 문서")
    index.close()


# --- 파이프라인 단위 ---------------------------------------------------------------------


def test_first_update_falls_back_to_a_full_build(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    index, stats = update_okf_index(bundle, tmp_path / "idx.sqlite3", V7)
    index.close()
    assert stats.full_rebuild
    assert stats.added == 2


def test_second_update_touches_nothing(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    db = tmp_path / "idx.sqlite3"
    update_okf_index(bundle, db, V7)[0].close()

    index, stats = update_okf_index(bundle, db, V7)
    index.close()
    assert not stats.full_rebuild
    assert stats.touched == 0
    assert stats.unchanged == 2
    assert stats.chunks_written == 0


def test_update_reindexes_only_the_changed_concept(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    db = tmp_path / "idx.sqlite3"
    update_okf_index(bundle, db, V7)[0].close()

    _write_concept(bundle, "doc-a", "완전히 새로운 본문 내용으로 바뀌었다.")
    index, stats = update_okf_index(bundle, db, V7)
    assert stats.updated == 1
    assert stats.added == 0
    assert stats.unchanged == 1
    assert index.search("완전히")
    # 옛 본문에만 있던 종목명. 한글 bigram 색인이라 겹치는 조각이 없는 단어를 골라야 한다.
    assert not index.search("에이피알")
    index.close()


def test_update_notices_a_new_concept(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    db = tmp_path / "idx.sqlite3"
    update_okf_index(bundle, db, V7)[0].close()

    _write_concept(bundle, "doc-c", "새로 들어온 세 번째 문서다.")
    index, stats = update_okf_index(bundle, db, V7)
    assert stats.added == 1 and stats.updated == 0 and stats.unchanged == 2
    assert index.search("세 번째")
    index.close()


def test_update_removes_a_deleted_concept_from_the_index(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    db = tmp_path / "idx.sqlite3"
    update_okf_index(bundle, db, V7)[0].close()

    (bundle / "commentary" / "doc-b.md").unlink()
    index, stats = update_okf_index(bundle, db, V7)
    assert stats.removed == 1
    assert not index.search("코스맥스")
    index.close()


def test_metadata_only_changes_still_trigger_reindexing(tmp_path: Path) -> None:
    """본문이 그대로여도 description은 청크 문맥으로 색인된다.

    원본 문서의 content_hash를 키로 삼았다면 이 변경을 놓쳐, 필터와 문맥이 조용히 옛 값으로
    남았을 것이다. 그래서 concept 파일 전체를 해시한다.
    """
    bundle = _bundle(tmp_path)
    db = tmp_path / "idx.sqlite3"
    update_okf_index(bundle, db, V7)[0].close()

    path = bundle / "commentary" / "doc-a.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("doc-a 요약", "새로 붙인 요약문"),
        encoding="utf-8",
    )
    index, stats = update_okf_index(bundle, db, V7)
    index.close()
    assert stats.updated == 1


def test_incremental_result_matches_a_full_rebuild(tmp_path: Path) -> None:
    """증분 갱신 결과가 전량 재구축과 같아야 한다 - 다르면 증분을 신뢰할 수 없다."""
    bundle = _bundle(tmp_path)
    incremental_db = tmp_path / "inc.sqlite3"
    update_okf_index(bundle, incremental_db, V7)[0].close()
    _write_concept(bundle, "doc-a", "바뀐 본문. 조금 더 길게 써서 청크 수도 달라지게 한다.")
    _write_concept(bundle, "doc-c", "새 문서 본문.")
    (bundle / "commentary" / "doc-b.md").unlink()
    inc_index, _ = update_okf_index(bundle, incremental_db, V7)

    full_index, _, _ = build_okf_index(bundle, tmp_path / "full.sqlite3", V7)

    def snapshot(index: Bm25Index) -> list[tuple]:
        return [
            (r["chunk_uid"], r["doc_id"], r["ord"], r["raw_hash"], r["ctx_hash"],
             r["entity_key"], r["okf_status"], r["native_doc_id"])
            for r in index.conn.execute(
                "SELECT * FROM chunk_meta ORDER BY chunk_uid")
        ]

    assert snapshot(inc_index) == snapshot(full_index)
    inc_index.close()
    full_index.close()


def test_native_doc_id_links_the_index_back_to_the_vault_document(tmp_path: Path) -> None:
    """"수집은 됐는데 색인 안 된 문서"를 정확히 세려면 이 연결이 필요하다."""
    bundle = tmp_path / "20_Knowledge"
    _write_concept(bundle, "doc-a", "본문", doc_id="vault-id-1")
    index, _, _ = build_okf_index(bundle, tmp_path / "idx.sqlite3", V7)
    assert index.indexed_native_ids() == {"vault-id-1"}
    index.close()


# --- run-daily 연결 ---------------------------------------------------------------------
# 이 호출이 없던 동안 색인은 손으로만 돌았고, 그래서 한 달 가까이 밀린 채 아무도 몰랐다.


def test_run_daily_updates_the_search_index_after_collecting(tmp_path: Path) -> None:
    from investor_intel.pipeline.orchestrator import update_search_index

    vault = tmp_path / "vault"
    _write_concept(vault / "20_Knowledge", "doc-a", "본문 내용입니다.")
    sqlite_path = tmp_path / "data" / "index.sqlite3"
    sqlite_path.parent.mkdir(parents=True)

    first = update_search_index(vault, sqlite_path)
    assert first is not None and "전량 재구축" in first
    assert (tmp_path / "data" / "search_index.sqlite3").exists()

    second = update_search_index(vault, sqlite_path)
    assert second is not None and "증분 갱신" in second


def test_run_daily_skips_the_index_when_there_is_no_bundle(tmp_path: Path) -> None:
    """검색 계층을 안 쓰는 설정에서 수집 자체를 실패시킬 이유는 없다."""
    from investor_intel.pipeline.orchestrator import update_search_index

    vault = tmp_path / "vault"
    (vault / "10_Sources").mkdir(parents=True)
    assert update_search_index(vault, tmp_path / "index.sqlite3") is None

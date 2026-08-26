from __future__ import annotations

from pathlib import Path

from investor_intel.indexing.bm25_index import Bm25Index


def _record(doc_id: str, body: str, *, okf_status: str = "stable",
           okf_type: str = "MarketCommentary", entity_key: str = "|kr-278470|",
           period_year: str = "2026", doc_path: str = "p") -> tuple[dict, str, str, str]:
    return (
        {"chunk_uid": f"{doc_id}#0", "doc_id": doc_id, "ord": 0, "doc_path": doc_path,
         "source_type": "telegram", "source_name": "s", "published_at": "2026-07-08",
         "title": "t", "filing_type": None, "capture_mode": "full", "heading_path": "",
         "kind": "prose", "n_chars": len(body), "raw_text": body,
         "okf_status": okf_status, "okf_type": okf_type, "entity_key": entity_key,
         "period_year": period_year, "pub_year": "2026"},
        "문맥", "t", body,
    )


def test_search_returns_the_okf_metadata_that_was_indexed(tmp_path: Path) -> None:
    """`Hit`가 이 넷을 담지 않으면, 인덱스에 저장된 okf_status가 있어도 호출부는 항상
    빈 문자열만 본다 - corrupt 문서를 근거로 걸러낼 방법이 없어진다."""
    index = Bm25Index(tmp_path / "idx.sqlite3")
    index.build([_record("a", "본문 내용", okf_status="corrupt", okf_type="DartFiling",
                          entity_key="|kr-000660|", period_year="2001")])

    (hit,) = index.search("본문")
    assert hit.okf_status == "corrupt"
    assert hit.okf_type == "DartFiling"
    assert hit.entity_key == "|kr-000660|"
    assert hit.period_year == "2001"
    index.close()


def test_search_documents_preserves_the_okf_metadata_of_the_winning_chunk(
    tmp_path: Path,
) -> None:
    """문서 단위 집계에서도 같은 필드가 살아 있어야 한다."""
    index = Bm25Index(tmp_path / "idx.sqlite3")
    index.build([_record("a", "본문 내용", okf_status="corrupt")])

    (hit,) = index.search_documents("본문")
    assert hit.okf_status == "corrupt"
    index.close()


def test_search_returns_the_doc_path_that_was_indexed(tmp_path: Path) -> None:
    """search()가 doc_path를 Hit에 채우지 않던 회귀 - search_documents()의 집계가
    best.doc_path를 읽는데, search()가 그 필드를 안 채우면 항상 빈 문자열이 된다."""
    index = Bm25Index(tmp_path / "idx.sqlite3")
    index.build([_record("a", "본문 내용", doc_path="10_Sources/DART/a.md")])

    (hit,) = index.search("본문")
    assert hit.doc_path == "10_Sources/DART/a.md"
    index.close()


def test_search_documents_preserves_doc_path_of_the_winning_chunk(tmp_path: Path) -> None:
    index = Bm25Index(tmp_path / "idx.sqlite3")
    index.build([_record("a", "본문 내용", doc_path="10_Sources/DART/a.md")])

    (hit,) = index.search_documents("본문")
    assert hit.doc_path == "10_Sources/DART/a.md"
    index.close()


def test_identical_chunk_text_across_documents_is_interned_but_reads_back_per_document(
    tmp_path: Path,
) -> None:
    """SEC 필링 표준 문구처럼 문서마다 본문이 완전히 같아도, chunk_text에는 한 벌만
    저장되고 각 문서는 여전히 자기 doc_id/메타데이터로 조회돼야 한다."""
    shared_body = "이 문단은 여러 문서에서 글자 하나까지 동일하게 반복된다"
    index = Bm25Index(tmp_path / "idx.sqlite3")
    index.build([
        _record("doc-a", shared_body, doc_path="a.md"),
        _record("doc-b", shared_body, doc_path="b.md"),
    ])

    n_texts = index.conn.execute("SELECT COUNT(*) FROM chunk_text").fetchone()[0]
    assert n_texts == 2  # 문맥("문맥") 하나 + 본문 하나 - 문서 2건이 본문을 공유해도 한 벌

    hits = {h.doc_id: h for h in index.search("반복")}
    assert hits["doc-a"].doc_path == "a.md"
    assert hits["doc-b"].doc_path == "b.md"
    assert hits["doc-a"].text == hits["doc-b"].text == shared_body
    index.close()


def test_exclude_status_filters_out_corrupt_chunks(tmp_path: Path) -> None:
    index = Bm25Index(tmp_path / "idx.sqlite3")
    index.build([
        _record("clean", "본문 내용", okf_status="stable"),
        _record("broken", "본문 내용", okf_status="corrupt"),
    ])

    all_hits = index.search("본문")
    assert {h.doc_id for h in all_hits} == {"clean", "broken"}

    filtered = index.search("본문", exclude_status=("corrupt",))
    assert {h.doc_id for h in filtered} == {"clean"}
    index.close()

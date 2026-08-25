from __future__ import annotations

from pathlib import Path

from investor_intel.indexing.bm25_index import Bm25Index


def _record(doc_id: str, body: str, *, okf_status: str = "stable",
           okf_type: str = "MarketCommentary", entity_key: str = "|kr-278470|",
           period_year: str = "2026") -> tuple[dict, str, str, str]:
    return (
        {"chunk_uid": f"{doc_id}#0", "doc_id": doc_id, "ord": 0, "doc_path": "p",
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

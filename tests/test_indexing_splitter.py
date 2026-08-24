from __future__ import annotations

from investor_intel.indexing.loader import LoadedDocument, Section
from investor_intel.indexing.splitter import context_header, split_document
from investor_intel.indexing.tokenizer import tokenize


def _doc(sections: list[Section]) -> LoadedDocument:
    return LoadedDocument(
        doc_id="d1", path="p", source_type="dart", source_name="005930",
        title="삼성전자 분기보고서", author="삼성전자", published_at="2026-05-15T00:00:00Z",
        language="ko", document_type="dart_filing", filing_type="분기보고서",
        reporting_period="2026-03-31", accession_number=None, companies=["005930"],
        capture_mode="full", source_url="http://x", sections=sections,
    )


def test_chunking_off_yields_single_unit() -> None:
    doc = _doc([Section("원문", "가" * 5000)])
    chunks = split_document(doc, chunking=False)
    assert len(chunks) == 1


def test_table_header_is_repeated_in_every_piece() -> None:
    rows = "\n".join(f"| 항목{i} | {i * 1000} |" for i in range(200))
    doc = _doc([Section("원문", f"| 항목 | 금액 |\n| --- | --- |\n{rows}")])
    chunks = split_document(doc, chunking=True, max_chars=400)
    tables = [c for c in chunks if c.kind == "table"]
    assert len(tables) > 1
    # 헤더가 빠지면 두 번째 조각부터는 숫자만 남아 근거로 쓸 수 없다
    assert all(c.text.startswith("| 항목 | 금액 |") for c in tables)


def test_documents_without_body_still_get_a_metadata_record() -> None:
    doc = _doc([])
    doc.capture_mode = "metadata_only"
    chunks = split_document(doc, chunking=True)
    assert len(chunks) == 1 and chunks[0].kind == "metadata"
    assert "삼성전자 분기보고서" in chunks[0].text


def test_context_header_carries_filterable_metadata() -> None:
    doc = _doc([Section("원문", "본문")])
    chunk = split_document(doc, chunking=True)[0]
    header = context_header(doc, chunk)
    for expected in ("dart", "005930", "분기보고서", "2026-03-31", "삼성전자 분기보고서"):
        assert expected in header


def test_korean_word_token_is_kept_alongside_bigrams() -> None:
    # bigram만 있으면 '영업이익'이 통째로 일치하는 문서에 점수를 몰아줄 수 없다
    assert tokenize("영업이익", korean_ngram=True) == ["영업", "업이", "이익"]
    assert "영업이익" in tokenize("영업이익", korean_ngram=True, korean_keep_word=True)
    assert tokenize("영업이익", korean_ngram=False) == ["영업이익"]


def test_identifier_is_indexed_whole_and_in_parts() -> None:
    toks = tokenize("accession 0001664703-22-000015")
    assert "0001664703-22-000015" in toks and "0001664703" in toks

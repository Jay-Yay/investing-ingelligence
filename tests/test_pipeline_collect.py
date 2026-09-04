from datetime import UTC, datetime

from investor_intel.collectors.base import CollectItem, CollectResult
from investor_intel.ingest.entities import EntityResolver
from investor_intel.models.common import SourceType
from investor_intel.pipeline.collect import collect_item_to_source_document, persist_collect_result
from investor_intel.storage.sqlite_index import connect, get_document_by_id, init_db


def _item(**overrides) -> CollectItem:
    defaults = dict(
        source_specific_id="acc-1",
        canonical_url="https://example.com/doc-1",
        title="Example title",
        author="Example Author",
        published_at=datetime(2026, 7, 24, tzinfo=UTC),
        updated_at=None,
        language="ko",
        body_text="본문 내용입니다.",
        content_capture_mode="full",
    )
    defaults.update(overrides)
    return CollectItem(**defaults)


def test_conversion_produces_valid_full_mode_document() -> None:
    doc, body = collect_item_to_source_document(
        _item(), source_type=SourceType.NAVER, source_name="engineerinvestor"
    )
    assert body == "본문 내용입니다."
    assert doc.content_capture.mode.value == "full"
    assert doc.content_capture.reason is None
    assert doc.source_type == SourceType.NAVER


def test_conversion_produces_valid_metadata_only_document() -> None:
    doc, _ = collect_item_to_source_document(
        _item(
            content_capture_mode="metadata_only",
            content_capture_reason="raw filing not parsed in this phase",
        ),
        source_type=SourceType.SEC_FILING,
        source_name="BE",
    )
    assert doc.content_capture.mode.value == "metadata_only"
    assert doc.content_capture.reason == "raw filing not parsed in this phase"


def test_persist_writes_document_and_index_row(tmp_path) -> None:
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    result = CollectResult(
        source_id="naver_x", success=True, items=[_item()], errors=[], new_count=1
    )
    persisted = persist_collect_result(
        result, source_type=SourceType.NAVER, source_name="engineerinvestor",
        vault_path=vault_path, conn=conn,
    )

    assert persisted.count == 1
    doc, _ = collect_item_to_source_document(
        _item(), source_type=SourceType.NAVER, source_name="engineerinvestor"
    )
    row = get_document_by_id(conn, doc.id)
    assert row is not None
    assert (vault_path).exists()


def test_persist_is_idempotent_on_rerun(tmp_path) -> None:
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    result = CollectResult(
        source_id="naver_x", success=True, items=[_item()], errors=[], new_count=1
    )
    persist_collect_result(
        result, source_type=SourceType.NAVER, source_name="engineerinvestor",
        vault_path=vault_path, conn=conn,
    )
    files_after_first = list(vault_path.rglob("*.md"))

    second = persist_collect_result(
        result, source_type=SourceType.NAVER, source_name="engineerinvestor",
        vault_path=vault_path, conn=conn,
    )
    files_after_second = list(vault_path.rglob("*.md"))

    # 내용이 그대로면 파일도 DB도 건드리지 않고 skipped로만 집계한다.
    assert second.count == 0
    assert second.skipped == 1
    assert files_after_first == files_after_second


def test_persist_reuses_existing_id_when_duplicate_detected_via_content_hash(tmp_path) -> None:
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    first_item = _item(source_specific_id="acc-1", canonical_url="https://example.com/doc-1")
    persist_collect_result(
        CollectResult(
            source_id="naver_x", success=True, items=[first_item], errors=[], new_count=1
        ),
        source_type=SourceType.NAVER, source_name="engineerinvestor",
        vault_path=vault_path, conn=conn,
    )

    # same content, but a different canonical_url and no source_specific_id this time —
    # find_duplicate must still catch it via content_hash and reuse the same id
    republished_item = _item(
        source_specific_id=None, canonical_url="https://example.com/doc-1-republished"
    )
    second = persist_collect_result(
        CollectResult(
            source_id="naver_x", success=True, items=[republished_item], errors=[], new_count=1
        ),
        source_type=SourceType.NAVER, source_name="engineerinvestor",
        vault_path=vault_path, conn=conn,
    )

    # 같은 내용이 다른 URL로 재게시된 것이므로 기존 id를 재사용하고 새 파일을 만들지 않는다.
    assert second.count == 0
    assert second.skipped == 1
    files = list(vault_path.rglob("*.md"))
    assert len(files) == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == 1


def test_persist_keeps_original_source_name_when_a_different_source_hits_the_same_document(
    tmp_path,
) -> None:
    # naver_research와 naver_weekly_hot처럼 서로 다른 source_name의 수집기가 같은
    # canonical_url(같은 리포트)을 가리킬 수 있다. find_duplicate는 canonical_url로
    # 기존 문서를 찾아 id를 재사용하는데, source_name까지 새 수집기 것으로 바꿔버리면
    # id(원래 source_name으로 해시)와 frontmatter의 source_name이 어긋난 문서가 된다.
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    original = _item(
        source_specific_id="96006", canonical_url="https://example.com/research/96006"
    )
    persist_collect_result(
        CollectResult(
            source_id="naver_research", success=True, items=[original], errors=[], new_count=1
        ),
        source_type=SourceType.IB_INSIGHTS, source_name="naver",
        vault_path=vault_path, conn=conn,
    )
    original_doc, _ = collect_item_to_source_document(
        original, source_type=SourceType.IB_INSIGHTS, source_name="naver"
    )

    # 다른 source_name, 다른 본문(다른 content_hash)이지만 같은 canonical_url.
    reranked = _item(
        source_specific_id="96006",
        canonical_url="https://example.com/research/96006",
        body_text="주간 인기 리포트로 다시 렌더링된 본문",
    )
    persist_collect_result(
        CollectResult(
            source_id="naver_weekly_hot", success=True, items=[reranked], errors=[], new_count=1
        ),
        source_type=SourceType.IB_INSIGHTS, source_name="naver-weekly-hot",
        vault_path=vault_path, conn=conn,
    )

    row = get_document_by_id(conn, original_doc.id)
    assert row is not None
    assert row["source_name"] == "naver"
    files = list(vault_path.rglob("*.md"))
    assert len(files) == 1


def _persist(vault_path, conn, item):
    return persist_collect_result(
        CollectResult(source_id="cb_boj", success=True, items=[item], errors=[], new_count=1),
        source_type=SourceType.CENTRAL_BANK,
        source_name="boj",
        vault_path=vault_path,
        conn=conn,
    )


def _vault_files(vault_path):
    return sorted(p for p in vault_path.rglob("*.md"))


def test_recollecting_same_document_with_new_published_at_does_not_duplicate_file(
    tmp_path,
) -> None:
    """`path_for_document`가 파일명을 published_at으로 만드는데, central_bank는 회의록이
    늦게 공개돼도 recency 창에 걸리도록 published_at=now를 쓴다. 그래서 재수집할 때마다
    경로가 달라져 같은 문서의 사본이 계속 쌓였다(실측: 271개 id / 초과 파일 678개 / 20.4MB).
    """
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    _persist(vault_path, conn, _item(published_at=datetime(2026, 8, 1, tzinfo=UTC)))
    second = _persist(vault_path, conn, _item(published_at=datetime(2026, 8, 5, tzinfo=UTC)))

    assert len(_vault_files(vault_path)) == 1
    # 내용이 같으므로 파일도 DB도 건드리지 않고 건너뛴다.
    assert second.count == 0
    assert second.skipped == 1


def test_recollected_document_with_changed_content_is_updated_in_place(tmp_path) -> None:
    """내용이 실제로 바뀐 재수집은 기존 파일을 제자리에서 갱신하고 재분석 대상으로 되돌린다."""
    vault_path = tmp_path / "vault"
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)

    _persist(vault_path, conn, _item(published_at=datetime(2026, 8, 1, tzinfo=UTC)))
    row = conn.execute("SELECT id, file_path FROM documents").fetchone()
    doc_id, original_path = row["id"], row["file_path"]
    conn.execute("UPDATE documents SET llm_processed = 1 WHERE id = ?", (doc_id,))
    conn.commit()

    result = _persist(
        vault_path,
        conn,
        _item(published_at=datetime(2026, 8, 5, tzinfo=UTC), body_text="개정된 본문입니다."),
    )

    assert result.count == 1
    assert result.skipped == 0
    assert len(_vault_files(vault_path)) == 1
    updated = get_document_by_id(conn, doc_id)
    # 경로는 그대로 유지하고, 내용이 달라졌으므로 재분석 대상으로 되돌린다.
    assert updated["file_path"] == original_path
    assert updated["llm_processed"] == 0
    assert "개정된 본문입니다." in (vault_path / original_path).read_text(encoding="utf-8")


# --- 수집 시점 품질 측정 / 종목 관계 해소 ------------------------------------------------
# 예전에는 두 판정을 하류의 OKF 번들 빌더에서만 했다. 그래서 vault 원문에는 "본문이 깨졌다",
# "이 문서는 어느 종목 얘기다"가 기록되지 않았고, 번들을 거치지 않는 소비자(analyze, 브리핑
# 작성)는 깨진 문서를 근거로 인용할 수 있었다.


def test_document_records_readable_ratio_at_collect_time() -> None:
    doc, _ = collect_item_to_source_document(
        _item(body_text="ab��"), source_type=SourceType.DART, source_name="278470"
    )
    assert doc.readable_ratio == 0.5


def test_clean_document_has_full_readable_ratio() -> None:
    doc, _ = collect_item_to_source_document(
        _item(), source_type=SourceType.NAVER, source_name="engineerinvestor"
    )
    assert doc.readable_ratio == 1.0
    assert doc.truncated is False
    assert doc.original_chars is None


def test_document_records_truncation_as_structured_metadata() -> None:
    body = "앞부분\n\n[...이하 생략, 원문 총 132,450자 중 40,000자까지만 캡처됨. 참고...]"
    doc, _ = collect_item_to_source_document(
        _item(body_text=body), source_type=SourceType.SEC_FILING, source_name="NBIS"
    )
    assert doc.truncated is True
    assert doc.original_chars == 132_450


def test_collector_declared_companies_become_the_documents_mentions() -> None:
    doc, _ = collect_item_to_source_document(
        _item(companies=["000660"]), source_type=SourceType.DART, source_name="000660"
    )
    assert doc.entities.mentions == ["000660"]
    assert doc.entities.subject == "000660"


def test_body_matching_recovers_mentions_when_the_source_provides_none() -> None:
    resolver = EntityResolver({"278470": "에이피알", "030610": "교보증권"})
    doc, _ = collect_item_to_source_document(
        _item(body_text="교보증권 리서치: 에이피알 목표주가 상향"),
        source_type=SourceType.TELEGRAM,
        source_name="kyobofnbcosmetic",
        resolver=resolver,
    )
    assert doc.entities.mentions == ["kr-278470"]
    assert doc.entities.analyst_house == ["kr-030610"]


def test_persist_populates_document_assets_from_the_resolved_entities(tmp_path) -> None:
    """`document_assets`가 0행이라 티커로 문서를 찾는 모든 조회가 빈 결과를 냈다.

    수집기가 `assets`를 채우는 곳이 하나도 없었기 때문이다 - 실제 종목 정보는 `companies`와
    본문에 있었다.
    """
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    result = CollectResult(source_id="dart_000660", success=True, items=[
        _item(companies=["000660"])], errors=[])
    persist_collect_result(result, SourceType.DART, "000660", tmp_path, conn)

    rows = conn.execute(
        "SELECT ticker, asset_type FROM document_assets ORDER BY ticker"
    ).fetchall()
    conn.close()
    assert [(r["ticker"], r["asset_type"]) for r in rows] == [("000660", "mention")]


def test_analyst_house_is_labelled_separately_in_document_assets(tmp_path) -> None:
    """분석 주체와 분석 대상이 같은 이름표를 달면 증권사로 필터링해 정답을 지운다."""
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    resolver = EntityResolver({"278470": "에이피알", "030610": "교보증권"})
    result = CollectResult(source_id="telegram_kyobo", success=True, items=[
        _item(body_text="교보증권 리서치: 에이피알 목표주가 상향")], errors=[])
    persist_collect_result(
        result, SourceType.TELEGRAM, "kyobofnbcosmetic", tmp_path, conn, resolver
    )

    rows = conn.execute(
        "SELECT ticker, asset_type FROM document_assets ORDER BY ticker"
    ).fetchall()
    conn.close()
    assert [(r["ticker"], r["asset_type"]) for r in rows] == [
        ("030610", "analyst_house"),
        ("278470", "mention"),
    ]

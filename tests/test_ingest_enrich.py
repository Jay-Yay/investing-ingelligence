from datetime import UTC, datetime
from pathlib import Path

from investor_intel.ingest.enrich import enrich_vault, enriched_document
from investor_intel.ingest.entities import EntityResolver
from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import ContentCapture, SourceDocument
from investor_intel.storage.obsidian_repo import read_document, write_document


def _doc(**overrides) -> SourceDocument:
    defaults = dict(
        id="abc123",
        source_type=SourceType.TELEGRAM,
        source_name="kyobofnbcosmetic",
        author="교보 음식료/화장품",
        title=None,
        source_url="https://t.me/kyobofnbcosmetic/1",
        source_specific_id="1",
        published_at=datetime(2026, 7, 8, tzinfo=UTC),
        collected_at=datetime(2026, 7, 8, tzinfo=UTC),
        language="ko",
        content_hash="hash-1",
        content_capture=ContentCapture(mode=ContentCaptureMode.FULL),
        document_type="opinion",
    )
    defaults.update(overrides)
    return SourceDocument(**defaults)


def _resolver() -> EntityResolver:
    return EntityResolver({"278470": "에이피알", "030610": "교보증권"})


def test_enrichment_fills_measurements_for_a_legacy_document() -> None:
    updated, _ = enriched_document(_doc(), "ab��", None)
    assert updated.readable_ratio == 0.5


def test_enrichment_recovers_mentions_for_a_document_with_no_companies() -> None:
    updated, recovered = enriched_document(
        _doc(), "교보증권 리서치: 에이피알 목표주가 상향", _resolver()
    )
    assert recovered is True
    assert updated.entities.mentions == ["kr-278470"]
    assert updated.entities.analyst_house == ["kr-030610"]


def test_enrichment_dedupes_companies_carried_over_from_metadata() -> None:
    """옛 13F 문서는 같은 종목이 보유 행 수만큼 반복돼 있다(실측 121개 항목 = 37개 종목)."""
    doc = _doc(source_type=SourceType.SEC_13F, companies=["APPLE INC"] * 12 + ["COCA COLA CO"])
    updated, recovered = enriched_document(doc, "본문", _resolver())
    assert recovered is False
    assert updated.entities.mentions == ["APPLE INC", "COCA COLA CO"]


def test_enrichment_never_rewrites_the_body_or_the_content_hash() -> None:
    doc = _doc()
    updated, _ = enriched_document(doc, "에이피알 실적", _resolver())
    assert updated.content_hash == doc.content_hash
    assert updated.id == doc.id


def test_enrichment_keeps_entities_that_are_already_present() -> None:
    doc, _ = enriched_document(_doc(), "에이피알 실적", _resolver())
    again, recovered = enriched_document(doc, "전혀 다른 본문 삼성전자", _resolver())
    assert recovered is False
    assert again.entities.mentions == doc.entities.mentions


def test_dry_run_counts_changes_without_touching_any_file(tmp_path: Path) -> None:
    write_document(tmp_path, _doc(), "교보증권 리서치: 에이피알 목표주가 상향")
    before = sorted(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.md"))

    stats = enrich_vault(tmp_path, conn=None, apply=False)

    assert stats.scanned == 1
    assert stats.updated == 1
    assert sorted(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.md")) == before


def test_apply_writes_the_measurements_into_the_frontmatter(tmp_path: Path) -> None:
    write_document(tmp_path, _doc(), "앞부분 [...이하 생략, 원문 총 9,000자 중 40자까지만 캡처됨.]")

    stats = enrich_vault(tmp_path, conn=None, apply=True)
    assert stats.updated == 1
    assert stats.truncated == 1

    (path,) = list(tmp_path.rglob("*.md"))
    reloaded, _ = read_document(path)
    assert reloaded.truncated is True
    assert reloaded.original_chars == 9_000


def test_apply_is_idempotent(tmp_path: Path) -> None:
    write_document(tmp_path, _doc(), "에이피알 실적")
    enrich_vault(tmp_path, conn=None, apply=True)
    second = enrich_vault(tmp_path, conn=None, apply=True)
    assert second.updated == 0


def test_corrupt_documents_are_reported_for_refetch(tmp_path: Path) -> None:
    """이 명령의 부산물: 재수집이 필요한 문서가 몇 건인지."""
    write_document(tmp_path, _doc(), "��" * 50)
    stats = enrich_vault(tmp_path, conn=None, apply=False)
    assert stats.corrupt == 1
    assert stats.by_source["telegram:corrupt"] == 1

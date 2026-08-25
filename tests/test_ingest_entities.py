import sqlite3

from investor_intel.ingest.entities import EntityResolver

# 실제 상장법인 명부 대신 최소 사전. 매칭 사전은 4자 이상 이름만 받는다(짧은 이름은 오탐).
_NAMES = {
    "278470": "에이피알",
    "030610": "교보증권",
    "000660": "에스케이하이닉스",
}


def _resolver() -> EntityResolver:
    return EntityResolver(_NAMES)


def test_resolver_recovers_mentions_that_the_source_never_provided() -> None:
    """텔레그램·블로그·IB 문서는 원본에 종목 정보가 아예 없다(실측 2,860건)."""
    entities = _resolver().resolve("에이피알 벌써 매출액 7,500억원, 속도 미쳤는데요?")
    assert entities.mentions == ["kr-278470"]


def test_resolver_splits_the_analyst_house_from_the_subject_companies() -> None:
    """교보증권은 리포트를 쓴 쪽이고 에이피알이 분석 대상이다.

    둘을 한 목록에 섞으면 분석 주체로 필터링해 정답 문서를 지운다(실측 실패 사례).
    """
    entities = _resolver().resolve("교보증권 리서치: 에이피알 목표주가 상향")
    assert entities.mentions == ["kr-278470"]
    assert entities.analyst_house == ["kr-030610"]


def test_resolver_records_the_lexicon_it_used() -> None:
    """사전이 바뀌면 매칭 결과도 바뀐다. 재현을 위해 어떤 사전이었는지 남긴다."""
    entities = _resolver().resolve("에이피알 실적")
    assert entities.lexicon_version == "dart-corp-codes:3"


def test_resolver_keeps_the_subject_it_is_given() -> None:
    entities = _resolver().resolve("에이피알 실적", subject="kyobofnbcosmetic")
    assert entities.subject == "kyobofnbcosmetic"


def test_empty_lexicon_is_reported_rather_than_silently_matching_nothing() -> None:
    """DART 캐시가 없는 머신에서는 관계 복원이 불가능하다 - 호출부가 알아야 한다."""
    assert EntityResolver({}).is_empty
    assert not _resolver().is_empty


def test_from_connection_survives_a_database_without_the_corp_code_cache() -> None:
    conn = sqlite3.connect(":memory:")
    resolver = EntityResolver.from_connection(conn)
    conn.close()
    assert resolver.is_empty
    assert resolver.resolve("에이피알 실적").mentions == []


def test_from_connection_reads_the_existing_corp_code_cache() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE dart_corp_codes (corp_code TEXT, corp_name TEXT, stock_code TEXT)"
    )
    conn.executemany(
        "INSERT INTO dart_corp_codes VALUES (?,?,?)",
        [("001", "에이피알", "278470"), ("002", "빈코드", "")],
    )
    resolver = EntityResolver.from_connection(conn)
    conn.close()
    assert resolver.resolve("에이피알 실적 발표").mentions == ["kr-278470"]

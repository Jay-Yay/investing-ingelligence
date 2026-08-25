from investor_intel.ingest.quality import (
    CORRUPT_RATIO_THRESHOLD,
    is_corrupt,
    readable_ratio,
    truncation_of,
)


def test_readable_ratio_is_one_for_clean_text() -> None:
    assert readable_ratio("주식회사 에이피알 분기보고서") == 1.0


def test_readable_ratio_is_one_for_empty_body() -> None:
    """본문이 없는 문서(stub)는 '깨졌다'가 아니라 '없다'다. 둘을 섞으면 안 된다."""
    assert readable_ratio("") == 1.0


def test_readable_ratio_counts_replacement_chars() -> None:
    # EUC-KR 한글 한 글자를 UTF-8로 잘못 읽으면 치환문자 두 개가 된다.
    assert readable_ratio("ab��") == 0.5


def test_is_corrupt_uses_the_shared_threshold() -> None:
    assert is_corrupt(1.0 - CORRUPT_RATIO_THRESHOLD - 0.01)
    assert not is_corrupt(1.0 - CORRUPT_RATIO_THRESHOLD)
    assert not is_corrupt(1.0)
    assert not is_corrupt(None)


def test_truncation_of_reads_the_original_length_back_from_the_body() -> None:
    """절단 사실이 본문 안 한국어 문장으로만 남아 있어 구조화된 소비자가 볼 수 없었다."""
    body = (
        "본문 앞부분\n\n[...이하 생략, 원문 총 132,450자 중 40,000자까지만 캡처됨. "
        "전체 원문은 출처 링크 참고...]"
    )
    truncated, original = truncation_of(body)
    assert truncated is True
    assert original == 132_450


def test_truncation_of_reports_no_truncation_for_a_full_body() -> None:
    assert truncation_of("짧은 본문") == (False, None)

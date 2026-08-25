from investor_intel.collectors.filing_kind import (
    classify_dart_report,
    classify_sec_form,
    title_prefix,
)


def test_classify_dart_report_matches_annual() -> None:
    assert classify_dart_report("사업보고서 (2023.12)") == "연간"


def test_classify_dart_report_matches_semiannual() -> None:
    assert classify_dart_report("반기보고서 (2025.06)") == "반기"


def test_classify_dart_report_matches_quarterly() -> None:
    assert classify_dart_report("분기보고서 (2024.03)") == "분기"


def test_classify_dart_report_returns_none_for_other_types() -> None:
    assert classify_dart_report("주요사항보고서(유상증자결정)") is None


def test_classify_sec_form_matches_annual_and_amendment() -> None:
    assert classify_sec_form("10-K") == "연간"
    assert classify_sec_form("10-K/A") == "연간"


def test_classify_sec_form_matches_quarterly_and_amendment() -> None:
    assert classify_sec_form("10-Q") == "분기"
    assert classify_sec_form("10-Q/A") == "분기"


def test_classify_sec_form_matches_fpi_annual_report() -> None:
    assert classify_sec_form("20-F") == "연간"
    assert classify_sec_form("20-F/A") == "연간"


def test_classify_sec_form_returns_none_for_other_forms() -> None:
    assert classify_sec_form("8-K") is None
    assert classify_sec_form("6-K") is None


def test_title_prefix_formats_when_present_and_empty_when_none() -> None:
    assert title_prefix("연간") == "[연간보고서] "
    assert title_prefix(None) == ""

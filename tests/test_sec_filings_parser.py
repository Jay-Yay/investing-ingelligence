import json
from pathlib import Path

from investor_intel.collectors.sec_filings_parser import parse_company_filings

FIXTURES = Path(__file__).parent / "fixtures" / "sec"


def _load() -> dict:
    return json.loads((FIXTURES / "submissions_company_test.json").read_text(encoding="utf-8"))


def test_filters_to_configured_forms_only() -> None:
    refs = parse_company_filings(_load(), forms=frozenset({"10-K", "10-Q", "8-K"}))
    assert len(refs) == 3
    assert all(r.form != "SC 13G" for r in refs)


def test_parses_8k_items_into_list() -> None:
    refs = parse_company_filings(_load(), forms=frozenset({"8-K"}))
    assert len(refs) == 1
    assert refs[0].items == ["2.02", "9.01"]


def test_empty_items_string_becomes_empty_list() -> None:
    refs = parse_company_filings(_load(), forms=frozenset({"10-K"}))
    assert len(refs) == 1
    assert refs[0].items == []


def test_tolerates_blank_report_date() -> None:
    refs = parse_company_filings(_load(), forms=frozenset({"8-K"}))
    assert refs[0].period_of_report is None


def test_populated_report_date_parses() -> None:
    refs = parse_company_filings(_load(), forms=frozenset({"10-Q"}))
    assert refs[0].period_of_report is not None
    assert refs[0].period_of_report.isoformat() == "2024-03-31"


def test_tolerates_missing_items_and_description_arrays() -> None:
    data = _load()
    del data["filings"]["recent"]["items"]
    del data["filings"]["recent"]["primaryDocDescription"]

    refs = parse_company_filings(data, forms=frozenset({"10-K", "10-Q", "8-K"}))
    assert len(refs) == 3
    assert all(r.items == [] for r in refs)
    assert all(r.primary_doc_description is None for r in refs)


def test_primary_document_and_accession_captured() -> None:
    refs = parse_company_filings(_load(), forms=frozenset({"10-K"}))
    assert refs[0].accession_number == "0001664703-23-000030"
    assert refs[0].primary_document == "form10k.htm"
    assert refs[0].primary_doc_description == "10-K"

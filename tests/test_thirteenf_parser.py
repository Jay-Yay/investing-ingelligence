import json
from pathlib import Path

import pytest

from investor_intel.collectors.thirteenf_parser import (
    list_xml_document_candidates,
    parse_information_table_xml,
    parse_submissions_filings,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sec"


def test_parse_submissions_filters_to_13f_hr_only() -> None:
    data = json.loads((FIXTURES / "submissions_1536411.json").read_text(encoding="utf-8"))
    refs = parse_submissions_filings(data)
    assert len(refs) == 3
    assert refs[0].accession_number == "0001536411-24-000007"
    assert refs[0].filing_date.isoformat() == "2024-05-15"
    assert refs[0].period_of_report.isoformat() == "2024-03-31"
    assert refs[0].form == "13F-HR"
    assert refs[0].primary_document == "primary_doc.xml"


def test_parse_submissions_excludes_other_forms() -> None:
    data = json.loads((FIXTURES / "submissions_1536411.json").read_text(encoding="utf-8"))
    data["filings"]["recent"]["form"][0] = "13F-HR/A"
    refs = parse_submissions_filings(data)
    assert len(refs) == 2
    assert all(r.form == "13F-HR" for r in refs)


def test_parse_information_table_current() -> None:
    xml_text = (FIXTURES / "form13fInfoTable_current.xml").read_text(encoding="utf-8")
    holdings = parse_information_table_xml(xml_text)
    assert len(holdings) == 3

    nvda = next(h for h in holdings if h.cusip == "67066G104")
    assert nvda.issuer == "NVIDIA CORP"
    assert nvda.value_usd_thousands == 1250000
    assert nvda.shares_or_principal_amount == 15000
    assert nvda.put_call is None

    tsla = next(h for h in holdings if h.cusip == "88160R101")
    assert tsla.put_call == "Call"
    assert tsla.voting_authority.sole == 5000


def test_parse_information_table_rejects_wrong_root() -> None:
    with pytest.raises(ValueError):
        parse_information_table_xml("<notInformationTable/>")


def test_list_xml_document_candidates_excludes_primary() -> None:
    index_json = json.loads(
        (FIXTURES / "index_0001536411-24-000007.json").read_text(encoding="utf-8")
    )
    candidates = list_xml_document_candidates(index_json, exclude="primary_doc.xml")
    assert candidates == ["form13fInfoTable.xml"]

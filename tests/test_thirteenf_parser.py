import json
from datetime import date
from pathlib import Path

import pytest

from investor_intel.collectors.thirteenf_parser import (
    list_xml_document_candidates,
    parse_information_table_xml,
    parse_submissions_filings,
    value_unit_for_filing_date,
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
    assert nvda.value_usd == 1250000
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


# --- 금액 단위 (2023-01-03 SEC 서식 개정) ---------------------------------------------
# 그 전 제출본의 <value>는 천 달러, 이후는 원 달러다. 구분하지 않으면 최근 필링 금액이
# 1,000배로 부풀고 연도가 섞인 시계열/랭킹 질의가 조용히 오답을 낸다.


def test_value_unit_is_thousands_before_2023_cutover() -> None:
    assert value_unit_for_filing_date(date(2022, 11, 14)) == 1_000
    assert value_unit_for_filing_date(date(2023, 1, 2)) == 1_000


def test_value_unit_is_whole_dollars_from_2023_cutover() -> None:
    assert value_unit_for_filing_date(date(2023, 1, 3)) == 1
    assert value_unit_for_filing_date(date(2024, 11, 14)) == 1


def test_parse_scales_pre_cutover_values_to_dollars() -> None:
    xml_text = (FIXTURES / "form13fInfoTable_current.xml").read_text(encoding="utf-8")
    old = parse_information_table_xml(xml_text, date(2022, 11, 14))
    new = parse_information_table_xml(xml_text, date(2024, 11, 14))
    assert [h.value_usd for h in old] == [h.value_usd * 1_000 for h in new]


def test_parse_without_filing_date_assumes_whole_dollars() -> None:
    """단위를 모를 때 1,000배 부풀리는 쪽보다 그대로 두는 쪽이 안전하다."""
    xml_text = (FIXTURES / "form13fInfoTable_current.xml").read_text(encoding="utf-8")
    assert parse_information_table_xml(xml_text) == parse_information_table_xml(
        xml_text, date(2024, 11, 14)
    )

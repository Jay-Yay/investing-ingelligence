from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import Any

from investor_intel.models.thirteenf import ThirteenFHolding, VotingAuthority


@dataclass
class FilingRef:
    accession_number: str
    filing_date: date
    period_of_report: date
    form: str
    primary_document: str


def parse_submissions_filings(
    submissions: dict[str, Any], forms: frozenset[str] = frozenset({"13F-HR"})
) -> list[FilingRef]:
    recent = submissions["filings"]["recent"]
    refs: list[FilingRef] = []
    for i, form in enumerate(recent["form"]):
        if form not in forms:
            continue
        refs.append(
            FilingRef(
                accession_number=recent["accessionNumber"][i],
                filing_date=date.fromisoformat(recent["filingDate"][i]),
                period_of_report=date.fromisoformat(recent["reportDate"][i]),
                form=form,
                primary_document=recent["primaryDocument"][i],
            )
        )
    return refs


# SEC는 2023-01-03 이후 제출되는 Form 13F의 <value>를 **천 달러가 아닌 원 달러**로 받는다
# (Form 13F 기술 개정). 그 전 제출본은 천 달러 단위다. 코드가 이걸 구분하지 않으면 최근
# 필링의 금액이 1,000배로 부풀고, 연도가 섞인 시계열/랭킹 질의가 조용히 오답을 낸다 -
# 실제로 vault의 2024-11-14 필링 머리글이 "총 보고 가치 266,378,900,503천 달러"(266조 달러)로
# 저장돼 있었다.
WHOLE_DOLLAR_CUTOVER = date(2023, 1, 3)


def value_unit_for_filing_date(filing_date: date) -> int:
    """원문 <value> 한 단위가 몇 달러인지 돌려준다 (1 또는 1,000)."""
    return 1 if filing_date >= WHOLE_DOLLAR_CUTOVER else 1_000


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _find_child(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if _local_tag(child) == name:
            return child
    return None


def _find_child_text(parent: ET.Element, name: str) -> str | None:
    child = _find_child(parent, name)
    return child.text if child is not None else None


def parse_information_table_xml(
    xml_text: str, filing_date: date | None = None
) -> list[ThirteenFHolding]:
    """정보표 XML을 행 목록으로 파싱한다. 금액은 달러 단위로 정규화한다.

    `filing_date`를 주지 않으면 원 달러(최신 규칙)로 간주한다 - 단위를 모르는 상태에서
    1,000배 부풀리는 쪽보다 그대로 두는 쪽이 안전하다.
    """
    value_multiplier = value_unit_for_filing_date(filing_date) if filing_date else 1
    root = ET.fromstring(xml_text)
    if _local_tag(root) != "informationTable":
        raise ValueError("not an informationTable document")

    holdings: list[ThirteenFHolding] = []
    for info_table in root:
        if _local_tag(info_table) != "infoTable":
            continue

        shrs_elem = _find_child(info_table, "shrsOrPrnAmt")
        if shrs_elem is None:
            raise ValueError("infoTable missing shrsOrPrnAmt")
        shares_amount = int(_find_child_text(shrs_elem, "sshPrnamt") or "0")
        shares_type = _find_child_text(shrs_elem, "sshPrnamtType") or ""

        voting_elem = _find_child(info_table, "votingAuthority")
        if voting_elem is None:
            raise ValueError("infoTable missing votingAuthority")
        voting_authority = VotingAuthority(
            sole=int(_find_child_text(voting_elem, "Sole") or "0"),
            shared=int(_find_child_text(voting_elem, "Shared") or "0"),
            none=int(_find_child_text(voting_elem, "None") or "0"),
        )

        holdings.append(
            ThirteenFHolding(
                issuer=_find_child_text(info_table, "nameOfIssuer") or "",
                title_of_class=_find_child_text(info_table, "titleOfClass") or "",
                cusip=_find_child_text(info_table, "cusip") or "",
                value_usd=int(_find_child_text(info_table, "value") or "0")
                * value_multiplier,
                shares_or_principal_amount=shares_amount,
                shares_or_principal_type=shares_type,
                put_call=_find_child_text(info_table, "putCall"),
                investment_discretion=_find_child_text(info_table, "investmentDiscretion") or "",
                other_manager=_find_child_text(info_table, "otherManager"),
                voting_authority=voting_authority,
            )
        )
    return holdings


def list_xml_document_candidates(index_json: dict[str, Any], exclude: str) -> list[str]:
    items = index_json.get("directory", {}).get("item", [])
    return [
        item["name"]
        for item in items
        if item["name"].lower().endswith(".xml") and item["name"] != exclude
    ]

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


def parse_information_table_xml(xml_text: str) -> list[ThirteenFHolding]:
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
                value_usd_thousands=int(_find_child_text(info_table, "value") or "0"),
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

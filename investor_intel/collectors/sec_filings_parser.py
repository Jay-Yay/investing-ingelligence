from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class CompanyFilingRef:
    accession_number: str
    filing_date: date
    period_of_report: date | None
    form: str
    primary_document: str
    primary_doc_description: str | None
    items: list[str]


def _parse_report_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _parse_items(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_company_filings(
    submissions: dict[str, Any], forms: frozenset[str]
) -> list[CompanyFilingRef]:
    recent = submissions["filings"]["recent"]
    descriptions = recent.get("primaryDocDescription")
    items_field = recent.get("items")

    refs: list[CompanyFilingRef] = []
    for i, form in enumerate(recent["form"]):
        if form not in forms:
            continue
        refs.append(
            CompanyFilingRef(
                accession_number=recent["accessionNumber"][i],
                filing_date=date.fromisoformat(recent["filingDate"][i]),
                period_of_report=_parse_report_date(recent["reportDate"][i]),
                form=form,
                primary_document=recent["primaryDocument"][i],
                primary_doc_description=(descriptions[i] if descriptions is not None else None),
                items=_parse_items(items_field[i] if items_field is not None else None),
            )
        )
    return refs

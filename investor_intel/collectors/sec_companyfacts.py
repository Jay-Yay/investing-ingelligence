from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

_CONCEPT_ALIASES: dict[str, list[str]] = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
    "net_income": ["NetIncomeLoss"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
}


@dataclass
class FinancialFact:
    concept: str
    val: float
    unit: str
    start: date | None
    end: date
    accn: str
    form: str
    fy: int
    fp: str


@dataclass
class FinancialStatementSnapshot:
    revenue: FinancialFact | None
    net_income: FinancialFact | None
    total_assets: FinancialFact | None
    total_liabilities: FinancialFact | None


def parse_companyfacts(
    data: dict[str, Any], taxonomy: str = "us-gaap"
) -> dict[str, list[FinancialFact]]:
    concepts = data.get("facts", {}).get(taxonomy, {})
    result: dict[str, list[FinancialFact]] = {}
    for concept, concept_data in concepts.items():
        usd_facts = concept_data.get("units", {}).get("USD")
        if not usd_facts:
            continue
        result[concept] = [
            FinancialFact(
                concept=concept,
                val=fact["val"],
                unit="USD",
                start=date.fromisoformat(fact["start"]) if "start" in fact else None,
                end=date.fromisoformat(fact["end"]),
                accn=fact["accn"],
                form=fact["form"],
                fy=fact["fy"],
                fp=fact["fp"],
            )
            for fact in usd_facts
        ]
    return result


def _find_fact(
    facts_by_concept: dict[str, list[FinancialFact]],
    aliases: list[str],
    accession_number: str,
    period_of_report: date,
) -> FinancialFact | None:
    for alias in aliases:
        for fact in facts_by_concept.get(alias, []):
            if fact.accn == accession_number and fact.end == period_of_report:
                return fact
    return None


def extract_financial_snapshot(
    facts_by_concept: dict[str, list[FinancialFact]],
    *,
    accession_number: str,
    period_of_report: date | None,
) -> FinancialStatementSnapshot:
    if period_of_report is None:
        return FinancialStatementSnapshot(
            revenue=None, net_income=None, total_assets=None, total_liabilities=None
        )

    return FinancialStatementSnapshot(
        revenue=_find_fact(
            facts_by_concept, _CONCEPT_ALIASES["revenue"], accession_number, period_of_report
        ),
        net_income=_find_fact(
            facts_by_concept, _CONCEPT_ALIASES["net_income"], accession_number, period_of_report
        ),
        total_assets=_find_fact(
            facts_by_concept, _CONCEPT_ALIASES["total_assets"], accession_number, period_of_report
        ),
        total_liabilities=_find_fact(
            facts_by_concept,
            _CONCEPT_ALIASES["total_liabilities"],
            accession_number,
            period_of_report,
        ),
    )

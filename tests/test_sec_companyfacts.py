import json
from datetime import date
from pathlib import Path

from investor_intel.collectors.sec_companyfacts import (
    extract_financial_snapshot,
    parse_companyfacts,
)
from investor_intel.collectors.sec_urls import companyfacts_url

FIXTURES = Path(__file__).parent / "fixtures" / "sec"


def _facts_by_concept() -> dict:
    data = json.loads((FIXTURES / "companyfacts_sample.json").read_text(encoding="utf-8"))
    return parse_companyfacts(data)


def test_companyfacts_url_uses_full_zero_padded_cik() -> None:
    assert (
        companyfacts_url("0000320193")
        == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    )


def test_parse_companyfacts_skips_non_usd_units() -> None:
    facts_by_concept = _facts_by_concept()
    assert "SomeNonUsdConcept" not in facts_by_concept
    assert "Revenues" in facts_by_concept
    assert "NetIncomeLoss" in facts_by_concept


def test_extract_financial_snapshot_prefers_modern_revenue_alias_when_both_exist() -> None:
    facts_by_concept = _facts_by_concept()

    snapshot = extract_financial_snapshot(
        facts_by_concept,
        accession_number="0000320193-24-000006",
        period_of_report=date(2023, 12, 30),
    )

    assert snapshot.revenue is not None
    assert snapshot.revenue.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_extract_financial_snapshot_disambiguates_same_accn_via_end_date() -> None:
    facts_by_concept = _facts_by_concept()

    snapshot = extract_financial_snapshot(
        facts_by_concept,
        accession_number="0000320193-24-000006",
        period_of_report=date(2023, 12, 30),
    )

    # two facts share this accn (3-month vs 6-month period); only the one whose `end`
    # matches period_of_report should be picked - both candidates end on 2023-12-30 here,
    # so the val must be one of the two, and the fact's own `end` must match exactly
    assert snapshot.revenue.end == date(2023, 12, 30)
    assert snapshot.revenue.val in (119575000000, 205468000000)


def test_extract_financial_snapshot_resolves_net_income_and_assets() -> None:
    facts_by_concept = _facts_by_concept()
    snapshot = extract_financial_snapshot(
        facts_by_concept,
        accession_number="0000320193-24-000006",
        period_of_report=date(2023, 12, 30),
    )

    assert snapshot.net_income is not None
    assert snapshot.net_income.val == 33916000000
    assert snapshot.total_assets is not None
    assert snapshot.total_assets.val == 353514000000


def test_extract_financial_snapshot_missing_concept_stays_none() -> None:
    facts_by_concept = _facts_by_concept()
    snapshot = extract_financial_snapshot(
        facts_by_concept,
        accession_number="0000320193-24-000006",
        period_of_report=date(2023, 12, 30),
    )
    assert snapshot.total_liabilities is None


def test_extract_financial_snapshot_returns_all_none_for_unmatched_accession() -> None:
    facts_by_concept = _facts_by_concept()
    snapshot = extract_financial_snapshot(
        facts_by_concept,
        accession_number="0000000000-00-000000",
        period_of_report=date(2024, 1, 1),
    )
    assert snapshot.revenue is None
    assert snapshot.net_income is None
    assert snapshot.total_assets is None
    assert snapshot.total_liabilities is None


def test_extract_financial_snapshot_handles_missing_period_of_report() -> None:
    facts_by_concept = _facts_by_concept()
    snapshot = extract_financial_snapshot(
        facts_by_concept,
        accession_number="0000320193-24-000006",
        period_of_report=None,
    )
    assert snapshot.revenue is None
    assert snapshot.net_income is None

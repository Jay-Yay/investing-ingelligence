from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.sec_client import SECClient
from investor_intel.collectors.sec_companyfacts import (
    FinancialFact,
    FinancialStatementSnapshot,
    extract_financial_snapshot,
    parse_companyfacts,
)
from investor_intel.collectors.filing_kind import classify_sec_form, title_prefix
from investor_intel.collectors.sec_document_fetch import fetch_full_text, find_transcript_exhibit
from investor_intel.collectors.sec_filings_document import render_sec_filing_body
from investor_intel.collectors.sec_filings_parser import CompanyFilingRef, parse_company_filings
from investor_intel.collectors.sec_urls import companyfacts_url, filing_index_page_url
from investor_intel.models.config import CompanyConfig

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

_CONTENT_CAPTURE_REASON = (
    "SEC filing HTML body is large and not parsed in this phase; "
    "canonical link provided for full text"
)


class SECFilingsCollector:
    def __init__(
        self,
        company: CompanyConfig,
        client: SECClient,
        checkpoint_store: CheckpointStore,
    ) -> None:
        self.source_id = f"sec_filings_{company.ticker.lower()}"
        self._company = company
        self._client = client
        self._checkpoint_store = checkpoint_store
        self._forms = frozenset(company.filing_types)
        self._companyfacts: dict[str, list[FinancialFact]] | None = None
        self._companyfacts_fetched = False

    def _fetch_all_filings(self) -> list[CompanyFilingRef]:
        submissions = self._client.get_json(_SUBMISSIONS_URL.format(cik=self._company.cik))
        return parse_company_filings(submissions, forms=self._forms)

    def _fetch_companyfacts(self) -> dict[str, list[FinancialFact]] | None:
        if not self._companyfacts_fetched:
            self._companyfacts_fetched = True
            try:
                data = self._client.get_json(companyfacts_url(self._company.cik))
                self._companyfacts = parse_companyfacts(data)
            except Exception:  # noqa: BLE001
                self._companyfacts = None
        return self._companyfacts

    def _snapshot_for(self, filing: CompanyFilingRef) -> FinancialStatementSnapshot | None:
        companyfacts = self._fetch_companyfacts()
        if companyfacts is None:
            return None
        return extract_financial_snapshot(
            companyfacts,
            accession_number=filing.accession_number,
            period_of_report=filing.period_of_report,
        )

    def _build_item(self, filing: CompanyFilingRef) -> CollectItem:
        canonical_url = filing_index_page_url(self._company.cik, filing.accession_number)
        snapshot = self._snapshot_for(filing)

        report_kind = classify_sec_form(filing.form)
        title_tag = title_prefix(report_kind)
        full_text: str | None = None
        is_transcript = False

        if report_kind is not None:
            full_text = fetch_full_text(
                self._client, self._company.cik, filing.accession_number, filing.primary_document
            )
        elif filing.form == "8-K":
            full_text = find_transcript_exhibit(
                self._client, self._company.cik, filing.accession_number
            )
            if full_text is not None:
                is_transcript = True
                title_tag = "[컨퍼런스콜] "

        body = render_sec_filing_body(
            filing,
            self._company,
            canonical_url,
            snapshot=snapshot,
            full_text=full_text,
            is_transcript=is_transcript,
        )

        published_at = datetime(
            filing.filing_date.year,
            filing.filing_date.month,
            filing.filing_date.day,
            tzinfo=UTC,
        )
        reporting_period_date = filing.period_of_report or filing.filing_date
        title = f"{title_tag}{self._company.name} {filing.form} ({reporting_period_date.isoformat()})"
        mode, reason = (
            ("full", None) if full_text is not None else ("metadata_only", _CONTENT_CAPTURE_REASON)
        )

        return CollectItem(
            source_specific_id=filing.accession_number,
            canonical_url=canonical_url,
            title=title,
            author=self._company.name,
            published_at=published_at,
            updated_at=None,
            language="en",
            body_text=body,
            content_capture_mode=mode,
            content_capture_reason=reason,
            companies=[self._company.ticker],
            document_type="sec_filing",
            filing_type=filing.form,
            reporting_period=(
                filing.period_of_report.isoformat() if filing.period_of_report else None
            ),
            accession_number=filing.accession_number,
        )

    def _collect(self, filings_to_process: list[CompanyFilingRef]) -> CollectResult:
        items: list[CollectItem] = []
        errors: list[str] = []
        for filing in filings_to_process:
            try:
                items.append(self._build_item(filing))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{filing.accession_number}: {exc}")

        if items:
            self._checkpoint_store.record_success(
                self.source_id, last_seen_id=items[-1].accession_number
            )
        elif errors:
            self._checkpoint_store.record_failure(self.source_id)

        return CollectResult(
            source_id=self.source_id,
            success=not errors,
            items=items,
            errors=errors,
            new_count=len(items),
        )

    def backfill(self, days: int) -> CollectResult:
        all_filings = self._fetch_all_filings()
        cutoff = date.today() - timedelta(days=days)
        to_process = sorted(
            (f for f in all_filings if f.filing_date >= cutoff),
            key=lambda f: f.filing_date,
        )
        result = self._collect(to_process)
        state = self._checkpoint_store.get_state(self.source_id)
        state.backfill_completed = True
        self._checkpoint_store.save_state(state)
        return result

    def collect_incremental(self) -> CollectResult:
        all_filings = self._fetch_all_filings()
        state = self._checkpoint_store.get_state(self.source_id)

        if state.last_seen_id is None:
            to_process = list(all_filings)
        else:
            last_seen_date = next(
                (
                    f.filing_date
                    for f in all_filings
                    if f.accession_number == state.last_seen_id
                ),
                None,
            )
            to_process = (
                list(all_filings)
                if last_seen_date is None
                else [f for f in all_filings if f.filing_date > last_seen_date]
            )

        to_process.sort(key=lambda f: f.filing_date)
        return self._collect(to_process)

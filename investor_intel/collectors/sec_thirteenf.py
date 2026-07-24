from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.sec_client import SECClient
from investor_intel.collectors.thirteenf_changes import compute_holding_changes
from investor_intel.collectors.thirteenf_document import render_thirteenf_body
from investor_intel.collectors.thirteenf_parser import (
    FilingRef,
    list_xml_document_candidates,
    parse_information_table_xml,
    parse_submissions_filings,
)
from investor_intel.models.config import InvestorConfig
from investor_intel.models.thirteenf import ThirteenFFiling, ThirteenFHolding

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data/{cik_short}/{accession_nodashes}"


def _cik_short(cik: str) -> str:
    return cik.lstrip("0") or "0"


def _accession_nodashes(accession_number: str) -> str:
    return accession_number.replace("-", "")


def _archive_dir(cik: str, accession_number: str) -> str:
    return _ARCHIVES_BASE.format(
        cik_short=_cik_short(cik), accession_nodashes=_accession_nodashes(accession_number)
    )


def _filing_index_url(cik: str, accession_number: str) -> str:
    return f"{_archive_dir(cik, accession_number)}/index.json"


def _filing_index_page_url(cik: str, accession_number: str) -> str:
    return f"{_archive_dir(cik, accession_number)}/{accession_number}-index.htm"


def _document_url(cik: str, accession_number: str, filename: str) -> str:
    return f"{_archive_dir(cik, accession_number)}/{filename}"


class ThirteenFCollector:
    def __init__(
        self,
        investor: InvestorConfig,
        client: SECClient,
        checkpoint_store: CheckpointStore,
    ) -> None:
        self.source_id = f"sec_13f_{investor.id}"
        self._investor = investor
        self._client = client
        self._checkpoint_store = checkpoint_store
        self._holdings_cache: dict[str, list[ThirteenFHolding]] = {}

    def _fetch_all_filings(self) -> list[FilingRef]:
        submissions = self._client.get_json(_SUBMISSIONS_URL.format(cik=self._investor.cik))
        return parse_submissions_filings(submissions)

    def _fetch_holdings(self, filing: FilingRef) -> list[ThirteenFHolding]:
        if filing.accession_number in self._holdings_cache:
            return self._holdings_cache[filing.accession_number]

        index_url = _filing_index_url(self._investor.cik, filing.accession_number)
        index_json = self._client.get_json(index_url)
        candidates = list_xml_document_candidates(index_json, exclude=filing.primary_document)

        holdings: list[ThirteenFHolding] | None = None
        for candidate in candidates:
            doc_url = _document_url(self._investor.cik, filing.accession_number, candidate)
            xml_text = self._client.get_text(doc_url)
            try:
                holdings = parse_information_table_xml(xml_text)
                break
            except ValueError:
                continue

        if holdings is None:
            raise ValueError(
                f"could not find an information table document for accession "
                f"{filing.accession_number}"
            )

        self._holdings_cache[filing.accession_number] = holdings
        return holdings

    def _find_previous(
        self, filing: FilingRef, all_filings: list[FilingRef]
    ) -> FilingRef | None:
        return next(
            (f for f in all_filings if f.period_of_report < filing.period_of_report), None
        )

    def _build_item(self, filing: FilingRef, all_filings: list[FilingRef]) -> CollectItem:
        current_holdings = self._fetch_holdings(filing)

        previous_ref = self._find_previous(filing, all_filings)
        previous_holdings = (
            self._fetch_holdings(previous_ref) if previous_ref is not None else None
        )

        thirteenf_filing = ThirteenFFiling(
            investor_id=self._investor.id,
            cik=self._investor.cik,
            accession_number=filing.accession_number,
            form_type=filing.form,
            filing_date=filing.filing_date,
            period_of_report=filing.period_of_report,
            holdings=current_holdings,
        )
        changes = compute_holding_changes(previous_holdings, current_holdings)
        canonical_url = _filing_index_page_url(self._investor.cik, filing.accession_number)
        body = render_thirteenf_body(thirteenf_filing, self._investor, changes, canonical_url)

        published_at = datetime(
            filing.filing_date.year,
            filing.filing_date.month,
            filing.filing_date.day,
            tzinfo=timezone.utc,
        )

        return CollectItem(
            source_specific_id=filing.accession_number,
            canonical_url=canonical_url,
            title=(
                f"{self._investor.fund_name} {filing.form} "
                f"({filing.period_of_report.isoformat()})"
            ),
            author=self._investor.fund_name,
            published_at=published_at,
            updated_at=None,
            language="en",
            body_text=body,
            content_capture_mode="full",
            companies=[h.issuer for h in current_holdings],
            document_type="13f_filing",
            filing_type=filing.form,
            reporting_period=filing.period_of_report.isoformat(),
            accession_number=filing.accession_number,
        )

    def _collect(
        self, filings_to_process: list[FilingRef], all_filings: list[FilingRef]
    ) -> CollectResult:
        items: list[CollectItem] = []
        errors: list[str] = []
        for filing in filings_to_process:
            try:
                items.append(self._build_item(filing, all_filings))
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
        result = self._collect(to_process, all_filings)
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
        return self._collect(to_process, all_filings)

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.dart_client import DartClient
from investor_intel.collectors.dart_document import render_dart_filing_body
from investor_intel.collectors.dart_filings_parser import DartFilingRef, parse_dart_list_response
from investor_intel.models.config import KoreanCompanyConfig

_LIST_URL = (
    "https://opendart.fss.or.kr/api/list.json?crtfc_key={api_key}&corp_code={corp_code}"
    "&bgn_de={bgn_de}&end_de={end_de}&pblntf_ty={report_type}"
    "&page_no={page_no}&page_count={page_count}"
)
_EARLIEST_BGN_DE = "19990101"
_PAGE_COUNT = 100

_CONTENT_CAPTURE_REASON = (
    "OpenDART filing original XML is not parsed in this phase; "
    "canonical DART viewer link provided for full text"
)


def _filing_viewer_url(rcept_no: str) -> str:
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


class DartCollector:
    def __init__(
        self,
        company: KoreanCompanyConfig,
        client: DartClient,
        checkpoint_store: CheckpointStore,
        api_key: str,
    ) -> None:
        self.source_id = f"dart_{company.ticker}"
        self._company = company
        self._client = client
        self._checkpoint_store = checkpoint_store
        self._api_key = api_key

    def _fetch_report_type(self, report_type: str, end_de: str) -> list[DartFilingRef]:
        refs: list[DartFilingRef] = []
        page_no = 1
        while True:
            url = _LIST_URL.format(
                api_key=self._api_key,
                corp_code=self._company.corp_code,
                bgn_de=_EARLIEST_BGN_DE,
                end_de=end_de,
                report_type=report_type,
                page_no=page_no,
                page_count=_PAGE_COUNT,
            )
            response = self._client.get_json(url)
            refs.extend(parse_dart_list_response(response))
            total_count = response.get("total_count", 0)
            if page_no * _PAGE_COUNT >= total_count:
                break
            page_no += 1
        return refs

    def _fetch_all_filings(self) -> list[DartFilingRef]:
        end_de = date.today().strftime("%Y%m%d")
        merged: dict[str, DartFilingRef] = {}
        for report_type in self._company.report_types:
            for ref in self._fetch_report_type(report_type, end_de):
                merged[ref.rcept_no] = ref
        return sorted(merged.values(), key=lambda r: r.rcept_dt)

    def _build_item(self, filing: DartFilingRef) -> CollectItem:
        canonical_url = _filing_viewer_url(filing.rcept_no)
        body = render_dart_filing_body(filing, canonical_url)
        published_at = datetime(
            filing.rcept_dt.year, filing.rcept_dt.month, filing.rcept_dt.day, tzinfo=UTC
        )

        return CollectItem(
            source_specific_id=filing.rcept_no,
            canonical_url=canonical_url,
            title=f"{filing.corp_name} {filing.report_nm} ({filing.rcept_dt.isoformat()})",
            author=filing.flr_nm,
            published_at=published_at,
            updated_at=None,
            language="ko",
            body_text=body,
            content_capture_mode="metadata_only",
            content_capture_reason=_CONTENT_CAPTURE_REASON,
            companies=[self._company.ticker],
            document_type="dart_filing",
            filing_type=filing.report_nm,
            reporting_period=filing.rcept_dt.isoformat(),
            accession_number=filing.rcept_no,
        )

    def _collect(self, filings_to_process: list[DartFilingRef]) -> CollectResult:
        items: list[CollectItem] = []
        errors: list[str] = []
        for filing in filings_to_process:
            try:
                items.append(self._build_item(filing))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{filing.rcept_no}: {exc}")

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
            (f for f in all_filings if f.rcept_dt >= cutoff), key=lambda f: f.rcept_dt
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
                (f.rcept_dt for f in all_filings if f.rcept_no == state.last_seen_id), None
            )
            to_process = (
                list(all_filings)
                if last_seen_date is None
                else [f for f in all_filings if f.rcept_dt > last_seen_date]
            )

        to_process.sort(key=lambda f: f.rcept_dt)
        return self._collect(to_process)

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.naver_research_document import render_naver_research_body
from investor_intel.collectors.naver_research_parser import (
    NaverResearchDetail,
    NaverResearchStub,
    parse_naver_research_detail,
    parse_naver_research_list,
)
from investor_intel.collectors.pdf_extract import PdfExtractError, extract_pdf_text
from investor_intel.models.config import SourceConfig

LIST_URL = "https://m.stock.naver.com/api/research/company"
_DETAIL_URL = "https://m.stock.naver.com/api/research/company/{research_id}"
_CANONICAL_URL = "https://m.stock.naver.com/research/company/{research_id}"

_EMPTY_DETAIL = NaverResearchDetail(
    content_text=None, opinion=None, goal_price=None, prev_goal_price=None, attach_url=None
)


class NaverResearchCollector:
    def __init__(
        self,
        source: SourceConfig,
        client: SimpleHttpClient,
        checkpoint_store: CheckpointStore,
    ) -> None:
        self.source_id = source.id
        self._source = source
        self._client = client
        self._checkpoint_store = checkpoint_store

    def _fetch_all_stubs(self) -> list[NaverResearchStub]:
        json_text = self._client.get_text(LIST_URL)
        return parse_naver_research_list(json_text)

    def _fetch_detail(self, research_id: int) -> NaverResearchDetail:
        try:
            json_text = self._client.get_text(_DETAIL_URL.format(research_id=research_id))
            return parse_naver_research_detail(json_text)
        except Exception:  # noqa: BLE001 - detail is best-effort, falls back to title-only
            return _EMPTY_DETAIL

    def _fetch_pdf_text(self, attach_url: str | None) -> str | None:
        if not attach_url:
            return None
        try:
            response = self._client.get(attach_url)
        except Exception:  # noqa: BLE001
            return None
        # sniff magic bytes rather than trust Content-Type - see ib_insights.py for why
        if not response.content.startswith(b"%PDF-"):
            return None
        try:
            return extract_pdf_text(response.content)
        except PdfExtractError:
            return None

    def _build_item(self, stub: NaverResearchStub) -> CollectItem:
        canonical_url = _CANONICAL_URL.format(research_id=stub.research_id)
        detail = self._fetch_detail(stub.research_id)
        pdf_text = self._fetch_pdf_text(detail.attach_url)
        body = render_naver_research_body(stub, detail, canonical_url, pdf_text)

        if pdf_text:
            mode, reason = "full", None
        elif detail.content_text:
            mode = "excerpt"
            reason = "PDF 원문 대신 네이버 API의 content 요약 필드만 캡처함"
        else:
            mode = "metadata_only"
            reason = "본문/PDF를 모두 가져오지 못해 제목만 캡처함"

        published = stub.write_date or date.today()
        return CollectItem(
            source_specific_id=str(stub.research_id),
            canonical_url=canonical_url,
            title=f"[{stub.item_name}] {stub.title}",
            author=stub.broker_name or self._source.name,
            published_at=datetime(published.year, published.month, published.day, tzinfo=UTC),
            updated_at=None,
            language="ko",
            body_text=body,
            content_capture_mode=mode,
            content_capture_reason=reason,
            companies=[stub.item_code] if stub.item_code else [],
            document_type="ib_research_summary",
            filing_type=None,
            reporting_period=None,
            accession_number=None,
        )

    def _collect(
        self, stubs_to_process: list[NaverResearchStub], checkpoint_id: str | None
    ) -> CollectResult:
        items: list[CollectItem] = []
        errors: list[str] = []
        for stub in stubs_to_process:
            try:
                items.append(self._build_item(stub))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{stub.research_id}: {exc}")

        if checkpoint_id is not None:
            self._checkpoint_store.record_success(self.source_id, last_seen_id=checkpoint_id)
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
        all_stubs = self._fetch_all_stubs()
        cutoff = date.today() - timedelta(days=days)
        to_process = [s for s in all_stubs if (s.write_date or date.today()) >= cutoff]
        checkpoint_id = str(all_stubs[0].research_id) if all_stubs else None
        result = self._collect(to_process, checkpoint_id)
        state = self._checkpoint_store.get_state(self.source_id)
        state.backfill_completed = True
        self._checkpoint_store.save_state(state)
        return result

    def collect_incremental(self) -> CollectResult:
        # same newest-first-list-walk strategy as IBInsightsCollector - see its
        # collect_incremental for why timestamp comparison isn't used instead.
        all_stubs = self._fetch_all_stubs()
        state = self._checkpoint_store.get_state(self.source_id)

        if state.last_seen_id is None:
            to_process = list(all_stubs)
        else:
            to_process = []
            for stub in all_stubs:
                if str(stub.research_id) == state.last_seen_id:
                    break
                to_process.append(stub)

        checkpoint_id = str(all_stubs[0].research_id) if all_stubs else state.last_seen_id
        return self._collect(to_process, checkpoint_id)

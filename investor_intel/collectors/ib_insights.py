from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.ib_insights_document import render_ib_insights_body
from investor_intel.collectors.ib_insights_parser import (
    IBArticle,
    find_citi_pdf_link,
    find_pdf_href,
    parse_blackrock_insights_index,
    parse_bofa_insights_index,
    parse_citi_insights_index,
    parse_gs_insights_index,
    parse_jpm_insights_index,
    parse_naver_research_index,
    parse_vanguard_insights_index,
)
from investor_intel.collectors.pdf_extract import PdfExtractError, extract_pdf_text
from investor_intel.models.config import SourceConfig

ParseIndexFn = Callable[[str], list[IBArticle]]
PdfLinkFinder = Callable[[str, str], str | None]


@dataclass
class IBInsightsSource:
    index_url: str
    parse_index: ParseIndexFn
    base_url: str
    pdf_link_finder: PdfLinkFinder | None = None
    language: str = "en"


# source.type -> registry entry. Shared by the collect pipeline (build_collect_entries) and the
# inbox resolver (pipeline/inbox.py), since both need the fixed index URL per bank.
IB_INSIGHTS_SOURCES: dict[str, IBInsightsSource] = {
    "gs_insights": IBInsightsSource(
        index_url="https://www.goldmansachs.com/insights",
        parse_index=parse_gs_insights_index,
        base_url="https://www.goldmansachs.com",
    ),
    "jpm_insights": IBInsightsSource(
        index_url="https://www.jpmorgan.com/insights/research",
        parse_index=parse_jpm_insights_index,
        base_url="https://www.jpmorgan.com",
    ),
    "bofa_insights": IBInsightsSource(
        index_url="https://business.bofa.com/en-us/content/institutional-investing-insights.html",
        parse_index=parse_bofa_insights_index,
        base_url="https://business.bofa.com",
        pdf_link_finder=find_pdf_href,
    ),
    "citi_insights": IBInsightsSource(
        index_url="https://www.citigroup.com/global/insights/citi-institute",
        parse_index=parse_citi_insights_index,
        base_url="https://www.citigroup.com",
        pdf_link_finder=find_citi_pdf_link,
    ),
    "blackrock_insights": IBInsightsSource(
        index_url="https://www.blackrock.com/us/individual/insights",
        parse_index=parse_blackrock_insights_index,
        base_url="https://www.blackrock.com",
        pdf_link_finder=find_pdf_href,
    ),
    "vanguard_insights": IBInsightsSource(
        index_url="https://investor.vanguard.com/investor-resources-education",
        parse_index=parse_vanguard_insights_index,
        base_url="https://investor.vanguard.com",
    ),
    "naver_research": IBInsightsSource(
        index_url="https://finance.naver.com/research/company_list.naver",
        parse_index=parse_naver_research_index,
        base_url="https://finance.naver.com",
        language="ko",
    ),
}


class IBInsightsCollector:
    def __init__(
        self,
        source: SourceConfig,
        client: SimpleHttpClient,
        checkpoint_store: CheckpointStore,
        index_url: str,
        parse_index: ParseIndexFn,
        base_url: str = "",
        pdf_link_finder: PdfLinkFinder | None = None,
        language: str = "en",
    ) -> None:
        self.source_id = source.id
        self._source = source
        self._client = client
        self._checkpoint_store = checkpoint_store
        self._index_url = index_url
        self._parse_index = parse_index
        self._base_url = base_url
        self._pdf_link_finder = pdf_link_finder
        self._language = language

    def _fetch_all_articles(self) -> list[IBArticle]:
        html_text = self._client.get_text(self._index_url)
        return self._parse_index(html_text)

    def _fetch_and_extract_pdf(self, pdf_link: str) -> str | None:
        try:
            response = self._client.get(pdf_link)
        except Exception:  # noqa: BLE001
            return None
        # some hosts (e.g. Naver's static file server) serve PDFs as generic
        # application/octet-stream rather than application/pdf, so sniff the file's own magic
        # bytes instead of trusting the server-declared Content-Type header.
        if not response.content.startswith(b"%PDF-"):
            return None
        try:
            return extract_pdf_text(response.content)
        except PdfExtractError:
            return None

    def _resolve_pdf_text(self, article: IBArticle) -> str | None:
        """Best-effort: use a PDF link already on the listing row if the parser found one
        (Naver research), otherwise fetch the article detail page and look for one there
        (BofA/BlackRock/Citi). Any failure along the way just falls back to the teaser
        (network errors, no link found, link doesn't actually resolve to a PDF, unreadable PDF)."""
        if article.pdf_url:
            return self._fetch_and_extract_pdf(article.pdf_url)

        if self._pdf_link_finder is None:
            return None
        try:
            detail_html = self._client.get_text(article.url)
        except Exception:  # noqa: BLE001
            return None

        pdf_link = self._pdf_link_finder(detail_html, self._base_url)
        if pdf_link is None:
            return None
        return self._fetch_and_extract_pdf(pdf_link)

    def _build_item(self, article: IBArticle) -> CollectItem:
        published = article.published_at or date.today()
        pdf_text = self._resolve_pdf_text(article)
        body = render_ib_insights_body(article, self._source, pdf_text=pdf_text)

        if pdf_text:
            mode, reason = "full", None
        elif article.summary:
            mode = "excerpt"
            reason = "인덱스 페이지 요약만 캡처 (첨부 PDF 없음, 원문 전체는 아님)"
        else:
            mode = "metadata_only"
            reason = "인덱스 페이지에 요약이 노출되지 않아 제목/링크만 캡처함"

        return CollectItem(
            source_specific_id=article.url,
            canonical_url=article.url,
            title=article.title,
            author=article.author or self._source.name,
            published_at=datetime(published.year, published.month, published.day, tzinfo=UTC),
            updated_at=None,
            language=self._language,
            body_text=body,
            content_capture_mode=mode,
            content_capture_reason=reason,
            companies=[],
            document_type="ib_research_summary",
            filing_type=None,
            reporting_period=None,
            accession_number=None,
        )

    def _collect(
        self, articles_to_process: list[IBArticle], checkpoint_id: str | None
    ) -> CollectResult:
        items: list[CollectItem] = []
        errors: list[str] = []
        for article in articles_to_process:
            try:
                items.append(self._build_item(article))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{article.url}: {exc}")

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
        all_articles = self._fetch_all_articles()
        cutoff = date.today() - timedelta(days=days)
        to_process = [a for a in all_articles if (a.published_at or date.today()) >= cutoff]
        checkpoint_id = all_articles[0].url if all_articles else None
        result = self._collect(to_process, checkpoint_id)
        state = self._checkpoint_store.get_state(self.source_id)
        state.backfill_completed = True
        self._checkpoint_store.save_state(state)
        return result

    def collect_incremental(self) -> CollectResult:
        # the listing has no reliable global timestamp (GS/BofA don't expose one at all), so
        # "new since last run" is determined by walking the newest-first list until the
        # previously recorded top article is found, rather than comparing published_at values.
        all_articles = self._fetch_all_articles()
        state = self._checkpoint_store.get_state(self.source_id)

        if state.last_seen_id is None:
            to_process = list(all_articles)
        else:
            to_process = []
            for article in all_articles:
                if article.url == state.last_seen_id:
                    break
                to_process.append(article)

        checkpoint_id = all_articles[0].url if all_articles else state.last_seen_id
        return self._collect(to_process, checkpoint_id)

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.ib_insights_document import render_ib_insights_body
from investor_intel.collectors.ib_insights_parser import (
    IBArticle,
    parse_bofa_insights_index,
    parse_gs_insights_index,
    parse_jpm_insights_index,
)
from investor_intel.models.config import SourceConfig

ParseIndexFn = Callable[[str], list[IBArticle]]

# source.type -> (index page URL, parser). Shared by the collect pipeline (build_collect_entries)
# and the inbox resolver (pipeline/inbox.py), since both need the fixed index URL per bank.
IB_INSIGHTS_SOURCES: dict[str, tuple[str, ParseIndexFn]] = {
    "gs_insights": (
        "https://www.goldmansachs.com/insights",
        parse_gs_insights_index,
    ),
    "jpm_insights": (
        "https://www.jpmorgan.com/insights/research",
        parse_jpm_insights_index,
    ),
    "bofa_insights": (
        "https://business.bofa.com/en-us/content/institutional-investing-insights.html",
        parse_bofa_insights_index,
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
    ) -> None:
        self.source_id = source.id
        self._source = source
        self._client = client
        self._checkpoint_store = checkpoint_store
        self._index_url = index_url
        self._parse_index = parse_index

    def _fetch_all_articles(self) -> list[IBArticle]:
        html_text = self._client.get_text(self._index_url)
        return self._parse_index(html_text)

    def _build_item(self, article: IBArticle) -> CollectItem:
        published = article.published_at or date.today()
        body = render_ib_insights_body(article, self._source)
        return CollectItem(
            source_specific_id=article.url,
            canonical_url=article.url,
            title=article.title,
            author=self._source.name,
            published_at=datetime(published.year, published.month, published.day, tzinfo=UTC),
            updated_at=None,
            language="en",
            body_text=body,
            content_capture_mode="excerpt" if article.summary else "metadata_only",
            content_capture_reason=(
                None
                if article.summary
                else "인덱스 페이지에 요약이 노출되지 않아 제목/링크만 캡처함"
            ),
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

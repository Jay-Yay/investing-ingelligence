from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.naver_document import render_naver_post_body
from investor_intel.collectors.naver_html_parser import fetch_post_body, fetch_posts_via_html
from investor_intel.collectors.naver_parser import (
    NaverPost,
    extract_blog_id,
    extract_log_no,
    parse_naver_rss,
)
from investor_intel.models.config import SourceConfig

_RSS_URL = "https://rss.blog.naver.com/{blog_id}.xml"


class NaverBlogCollector:
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
        self._blog_id = extract_blog_id(source.url)

    def _fetch_all_posts(self) -> list[NaverPost]:
        try:
            xml_text = self._client.get_text(_RSS_URL.format(blog_id=self._blog_id))
            posts = parse_naver_rss(xml_text)
            if posts:
                return posts
        except Exception:  # noqa: BLE001
            pass
        return fetch_posts_via_html(self._client, self._blog_id)

    def _build_item(self, post: NaverPost) -> CollectItem:
        log_no = extract_log_no(post.guid or post.link)
        body_text = fetch_post_body(self._client, self._blog_id, log_no)
        full_post = replace(post, description=body_text)
        body = render_naver_post_body(full_post, self._source, full_post.link)

        return CollectItem(
            source_specific_id=post.guid,
            canonical_url=post.link,
            title=post.title,
            author=self._source.author,
            published_at=post.published_at,
            updated_at=None,
            language="ko",
            body_text=body,
            content_capture_mode="full",
            companies=[],
            document_type="blog_post",
            filing_type=None,
            reporting_period=None,
            accession_number=None,
        )

    def _collect(self, posts_to_process: list[NaverPost]) -> CollectResult:
        items: list[CollectItem] = []
        errors: list[str] = []
        for post in posts_to_process:
            try:
                items.append(self._build_item(post))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{post.guid}: {exc}")

        if items:
            self._checkpoint_store.record_success(
                self.source_id, last_seen_id=items[-1].source_specific_id
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
        all_posts = self._fetch_all_posts()
        cutoff = date.today() - timedelta(days=days)
        to_process = sorted(
            (p for p in all_posts if p.published_at.date() >= cutoff),
            key=lambda p: p.published_at,
        )
        result = self._collect(to_process)
        state = self._checkpoint_store.get_state(self.source_id)
        state.backfill_completed = True
        self._checkpoint_store.save_state(state)
        return result

    def collect_incremental(self) -> CollectResult:
        all_posts = self._fetch_all_posts()
        state = self._checkpoint_store.get_state(self.source_id)

        if state.last_seen_id is None:
            to_process = list(all_posts)
        else:
            last_seen_published_at = next(
                (p.published_at for p in all_posts if p.guid == state.last_seen_id), None
            )
            to_process = (
                list(all_posts)
                if last_seen_published_at is None
                else [p for p in all_posts if p.published_at > last_seen_published_at]
            )

        to_process.sort(key=lambda p: p.published_at)
        return self._collect(to_process)

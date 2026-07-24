# Naver Blog + Telegram Collector Implementation Plan

**Goal:** Build the Naver blog and Telegram channel collectors, both conforming to `Collector`,
same shape as phases 02-04 (`CollectResult`/`CheckpointStore` idempotency contract, no direct
vault/index writes).

**Scope decisions (MVP, mirrors phases 03/04's metadata/full-capture scoping):**
- **Naver:** RSS only (`https://rss.blog.naver.com/{blogId}.xml`). Mobile-HTML fallback (needed
  only if a blog's RSS is disabled) is out of scope for this phase — it requires a second,
  materially different scraper (Naver mobile posts render body content inside an iframe requiring
  a follow-up `PostView.naver` request) and no currently configured source needs it.
- **Telegram:** public web preview only (`https://t.me/s/{channel}`, no auth). Telethon-based
  full history/private-channel collection is explicitly optional per the design doc and out of
  scope here. Pagination via the preview page's `?before={message_id}` param is also deferred —
  only the single most recent page (~20 messages) is visible to `backfill`/`collect_incremental`
  in this phase. Both are documented limitations, not oversights.
- Both collectors capture `content_capture_mode="full"` (RSS description / preview message text
  as provided by the source, not scraped/rendered separately).

## Global constraints

Inherited from phases 01-04 (still binding): no live network calls in tests (`respx` mocks all
`httpx` traffic); no placeholders/TODOs; collectors never read/write the vault or SQLite index
directly.

New for this phase:
- Neither source requires an API key or special header — a third, undecorated retrying HTTP
  client (`SimpleHttpClient`) is introduced and shared by both collectors (the first two sources,
  SEC/DART, each needed source-specific auth validation baked into their clients; a third
  identical-shape client is the point past which sharing beats duplicating).
- `SourceConfig.url` (already exists, Core Foundation) is the only per-source identity: for
  Naver it's the mobile blog URL the blog id is extracted from (last path segment); for Telegram
  it's already the `https://t.me/s/{channel}` preview URL used directly.

## Task breakdown

### Task 1: Shared `SimpleHttpClient`

**Files:** create `investor_intel/collectors/http_client.py`; test
`tests/test_http_client.py`.

**Interfaces:** `HttpClientError(Exception)`; `SimpleHttpClient(user_agent: str = "Investor
Intel/0.1", rate_limiter=None, http_client: httpx.Client | None = None)` with `.get_text(url) ->
str`, `.close() -> None`. Same retry-on-{429,500,502,503,504} shape as `SECClient`/`DartClient`;
no construction-time validation (no auth to validate).

- [x] Write failing tests, implement, verify pass
- [x] Commit: `feat: add shared no-auth retrying HTTP client for naver/telegram collectors`

### Task 2: Naver RSS parser

**Files:** create `investor_intel/collectors/naver_parser.py`; fixture
`tests/fixtures/naver/rss_feed.xml`; test `tests/test_naver_parser.py`.

**Interfaces:** `NaverPost` (dataclass): `guid: str, title: str, link: str, description: str,
published_at: datetime`. `parse_naver_rss(xml_text: str) -> list[NaverPost]` — standard RSS 2.0
`channel/item` list; `pubDate` parsed via `email.utils.parsedate_to_datetime` (stdlib, handles
RFC 822 dates robustly, including the `+0900` KST offset Naver uses).
`extract_blog_id(source_url: str) -> str` — last path segment of the source's mobile blog URL.

- [x] Write failing tests (parses title/link/description/guid; `pubDate` → tz-aware `datetime`;
      blog id extraction from a mobile URL), implement, verify pass
- [x] Commit: `feat: add Naver blog RSS parser`

### Task 3: Naver document renderer

**Files:** create `investor_intel/collectors/naver_document.py`; test
`tests/test_naver_document.py`.

**Interfaces:** `NAVER_LIMITATIONS_NOTE: str` (RSS-only scope, no images/attachments, mobile-HTML
fallback not implemented). `render_naver_post_body(post: NaverPost, source: SourceConfig,
canonical_url: str) -> str` — same 8-section Markdown shape as prior renderers.

- [x] Write failing tests, implement, verify pass
- [x] Commit: `feat: add Naver blog post Markdown renderer`

### Task 4: `NaverBlogCollector`

**Files:** create `investor_intel/collectors/naver_blog.py`; test
`tests/test_naver_blog.py`.

**Interfaces:** `NaverBlogCollector(source: SourceConfig, client: SimpleHttpClient,
checkpoint_store: CheckpointStore)` with `.source_id = source.id`, `.backfill(days) ->
CollectResult`, `.collect_incremental() -> CollectResult`. `CollectItem`: `source_specific_id` =
guid, `canonical_url` = post link, `language` = `"ko"`, `content_capture_mode` = `"full"`,
`document_type` = `"blog_post"`, `companies` = `[]` (not knowable without content analysis, left
for the LLM phase), `filing_type`/`reporting_period`/`accession_number` = `None` (not filing
documents). Same checkpoint idempotency contract as prior collectors.

- [x] Write failing tests (backfill day-window; incremental idempotency; source_id ==
      source.id), implement, verify pass
- [x] Commit: `feat: add NaverBlogCollector`

### Task 5: Telegram HTML parser

**Files:** create `investor_intel/collectors/telegram_parser.py`; fixture
`tests/fixtures/telegram/channel_preview.html`; test `tests/test_telegram_parser.py`.

**Interfaces:** `TelegramMessage` (dataclass): `message_id: str, channel: str, text: str, link:
str, published_at: datetime`. `parse_telegram_channel_html(html_text: str, channel: str) ->
list[TelegramMessage]` — a small `html.parser.HTMLParser` subclass tracking div-nesting depth to
correctly bound each `tgme_widget_message` container (message id from its `data-post` attribute)
and its nested `tgme_widget_message_text` div (message body, `<br>` → `\n`), plus the sibling
`<a class="tgme_widget_message_date" href=...>`/`<time datetime=...>` for link/timestamp.
Messages with empty/whitespace-only text (media-only posts) are skipped — no text to analyze
downstream.

- [ ] Write failing tests against a realistic 2-message fixture (nested `<b>`/`<br>` inside
      message text extracts correctly; link/timestamp attached to the right message; an
      empty-text message is skipped), implement, verify pass
- [ ] Commit: `feat: add Telegram channel web-preview HTML parser`

### Task 6: Telegram document renderer

**Files:** create `investor_intel/collectors/telegram_document.py`; test
`tests/test_telegram_document.py`.

**Interfaces:** `TELEGRAM_LIMITATIONS_NOTE: str` (public preview only, single page / most recent
messages only, no Telethon full-history). `render_telegram_message_body(message:
TelegramMessage, source: SourceConfig, canonical_url: str) -> str` — same 8-section shape.

- [ ] Write failing tests, implement, verify pass
- [ ] Commit: `feat: add Telegram message Markdown renderer`

### Task 7: `TelegramCollector`

**Files:** create `investor_intel/collectors/telegram.py`; test `tests/test_telegram.py`.

**Interfaces:** `TelegramCollector(source: SourceConfig, client: SimpleHttpClient,
checkpoint_store: CheckpointStore)` with `.source_id = source.id`, `.backfill(days) ->
CollectResult`, `.collect_incremental() -> CollectResult`. Channel name extracted from
`source.url` (`https://t.me/s/{channel}` → last path segment). `CollectItem`:
`source_specific_id` = `message_id`, `language` = `"ko"`, `content_capture_mode` = `"full"`,
`document_type` = `"telegram_message"`, `companies` = `[]`. Same checkpoint idempotency
contract.

- [ ] Write failing tests (backfill day-window; incremental idempotency; source_id == source.id),
      implement, verify pass
- [ ] Commit: `feat: add TelegramCollector`

### Task 8: Full verification pass

- [ ] `uv run pytest -v` — all tests green
- [ ] `uv run ruff check .` — clean
- [ ] `uv run mypy investor_intel` — clean
- [ ] Commit any fixes; update roadmap status for phase 05 to "merged to main"

## Self-review notes

- **No storage coupling:** neither collector imports `obsidian_repo`/`sqlite_index` for writing.
- **Reuse over duplication:** `SimpleHttpClient` is shared by both collectors rather than
  duplicated a third time (the point at which sharing wins per this project's stated
  three-strikes convention).
- **Deferred, not skipped:** Naver mobile-HTML fallback, Telegram pagination, and Telethon
  integration are named out-of-scope items with a stated reason, not silently dropped.

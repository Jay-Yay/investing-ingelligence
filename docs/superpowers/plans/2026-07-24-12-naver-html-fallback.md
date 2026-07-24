# Naver Mobile/PC HTML Fallback Implementation Plan

**Goal:** `NaverBlogCollector` currently depends solely on `rss.blog.naver.com/{blogId}.xml`. Some
blogs disable RSS, and RSS entries are sometimes summary-only. This phase adds a fallback that
works whenever RSS fails or returns nothing, using Naver's own public (undocumented but
unauthenticated, no login/cookie required) endpoints — confirmed live via `curl -A "Mozilla/5.0
..."` against a real blog (`engineerinvestor`) during research:

- **List discovery** — `GET https://blog.naver.com/PostTitleListAsync.naver?blogId={blogId}&currentPage={n}&categoryNo=&parentCategoryNo=&countPerPage=30`
  returns JSON `{"resultCode": "S", "postList": [{"logNo": "224355263150", "title": "...url-encoded...", "addDate": "2026. 7. 23." | "6시간 전", ...}, ...]}`.
  `addDate` is unusable as a real timestamp — Naver mixes relative strings ("N시간 전", "N일 전")
  for recent posts with date-only (no time) absolute strings for older ones. This endpoint is used
  **only** to discover `logNo`s, never to source a `published_at`.
- **Post detail** — `GET https://blog.naver.com/PostView.naver?blogId={blogId}&logNo={logNo}`
  returns the full rendered HTML (SmartEditor 3 markup) containing:
  - Title: `<div class="se-module se-module-text se-title-text">` wrapping a single
    `se-text-paragraph` `<p>`.
  - Publish timestamp: `<span class="se_publishDate ...">2026. 7. 23. 11:30</span>` — always
    absolute, always includes time, no timezone marker (Naver blogs are KST-only; treat as
    `Asia/Seoul`).
  - Body: `<div class="se-main-container">` containing one or more `se-component` blocks, each
    with `se-text-paragraph` `<p>` tags carrying the actual paragraph text (nested in `<span>`s).

**Scope decisions:**
- No new dependency. Every other collector in this repo (`telegram_parser.py`) parses HTML with
  stdlib `html.parser.HTMLParser` — this phase follows the same convention rather than adding
  `beautifulsoup4`/`lxml`.
- The list endpoint is paginated 30-at-a-time and has no known upper bound. Rather than paginate
  until exhaustion (unbounded, and this blog's RSS-equivalent history isn't needed for incremental
  collection), cap discovery at `_HTML_FALLBACK_MAX_PAGES = 3` (90 posts), stopping early if a
  page's `postList` is empty. This comfortably covers any real backfill window (`--days` is
  usually ≤ 90) and any realistic incremental gap; document the cap as a known limitation rather
  than engineering true pagination-to-exhaustion.
- Only activates as a fallback: `_fetch_all_posts` tries RSS first (existing behavior, wrapped in
  try/except), and only calls the HTML path if RSS raised or returned an empty list. RSS remains
  preferred because it's a single request instead of `1 + len(posts)` requests.
- Reuse the existing `NaverPost` dataclass and `render_naver_post_body` unchanged — the HTML path
  produces the same shape (`guid`, `title`, `link`, `description`, `published_at`), so
  `NaverBlogCollector._build_item`/`_collect`/`backfill`/`collect_incremental` need zero changes.
- Update `NAVER_LIMITATIONS_NOTE` in `naver_document.py` to drop the now-false "모바일 HTML
  폴백은 이 단계에서 구현하지 않는다" line and note the 90-post discovery cap instead.

## Task breakdown

### Task 1: `collectors/naver_html_parser.py`

**Files:** create `investor_intel/collectors/naver_html_parser.py`; test
`tests/test_naver_html_parser.py`; fixtures `tests/fixtures/naver/post_title_list_page1.json`,
`tests/fixtures/naver/post_title_list_empty.json`, `tests/fixtures/naver/post_view.html` (trimmed
down from real captured HTML — keep the surrounding structure realistic but drop unrelated
boilerplate: nav chrome, unrelated `<script>`/`<style>` blocks — the tests must exercise the real
element structure, not a hand-simplified stand-in).

**Interfaces:**
- `parse_post_log_nos(json_text: str) -> list[str]` — `json.loads`, returns
  `[p["logNo"] for p in postList]`, `[]` if `postList` missing/empty.
- `parse_post_detail_html(html_text: str) -> NaverPost` (reusing the `NaverPost` dataclass from
  `naver_parser.py`; `guid` and `link` are filled in by the caller, which knows `blogId`/`logNo` —
  so this function actually returns a purpose-built tuple/dataclass of `(title, body_text,
  published_at)`, and the orchestration function below assembles the final `NaverPost`) — parses
  title from `se-title-text`'s paragraph, body from every `se-text-paragraph` inside
  `se-main-container` (paragraphs joined with blank lines), and `published_at` from
  `se_publishDate`'s text (`"YYYY. M. D. HH:MM"`, parsed with `datetime.strptime` using a
  Korean-dot format string, tagged `tzinfo=ZoneInfo("Asia/Seoul")`).
- `fetch_posts_via_html(client: SimpleHttpClient, blog_id: str) -> list[NaverPost]` — pages
  through `PostTitleListAsync.naver` (up to `_HTML_FALLBACK_MAX_PAGES`, stopping early on an empty
  page), fetches `PostView.naver` for every discovered `logNo`, and returns fully assembled
  `NaverPost`s (`guid=logNo`, `link=f"https://blog.naver.com/{blog_id}/{logNo}"`).

- [x] Write failing tests (`parse_post_log_nos` on a real-shaped multi-post JSON fixture and on an
      empty-`postList` fixture; `parse_post_detail_html`-equivalent parsing on the trimmed real
      `post_view.html` fixture asserts exact title, a known paragraph substring, and the exact
      parsed KST datetime; `fetch_posts_via_html` against a mocked `SimpleHttpClient`/`respx`
      covering: single page then empty page (stops pagination), and hitting the
      `_HTML_FALLBACK_MAX_PAGES` cap without an empty page in between), implement, verify pass
- [x] Commit: `feat: add Naver blog HTML fallback parser`

### Task 2: Wire fallback into `NaverBlogCollector`

**Files:** modify `investor_intel/collectors/naver_blog.py`, `naver_document.py`; extend
`tests/test_naver_blog.py`.

`_fetch_all_posts` tries `parse_naver_rss` first; if it raises **or** returns `[]`, falls back to
`fetch_posts_via_html`. Update `NAVER_LIMITATIONS_NOTE` to remove the stale "not implemented" line
and add a note about the 90-post HTML-fallback discovery cap.

- [ ] Write a failing test (RSS endpoint mocked to return a 404/empty feed; HTML fallback endpoints
      mocked with real-shaped fixtures; `backfill`/`collect_incremental` still produce the correct
      `CollectResult` via the fallback path), implement, verify pass
- [ ] Commit: `feat: fall back to HTML scraping when Naver RSS is unavailable`

## Self-review notes

- **Verified against the live site, not guessed:** every selector/endpoint above was confirmed via
  direct `curl` against a real blog during research — not inferred from Naver's official docs
  (there are none) or from memory of a different blog platform.
- **No new dependency, matches existing convention:** `telegram_parser.py` already established
  stdlib `HTMLParser` as this repo's house style for scraping widget/preview HTML; this phase
  follows it instead of introducing `bs4`.
- **Bounded, not exhaustive, discovery:** the 90-post pagination cap is a deliberate, documented
  scope limit, not an oversight — true unbounded pagination isn't needed for backfill/incremental
  use cases and would risk hammering an endpoint with no documented rate-limit contract.

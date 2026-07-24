# Telegram Public Preview Pagination Implementation Plan

**Goal:** Phase 05 deliberately deferred this: `TelegramCollector._fetch_all_messages` fetches
only `https://t.me/s/{channel}` once, exposing just the single most recent page (~20 messages) to
both `backfill` and `collect_incremental` — "pagination via the preview page's
`?before={message_id}` param is also deferred... Both are documented limitations, not oversights"
(`docs/superpowers/plans/2026-07-24-05-naver-telegram-collectors.md`). This phase adds that
pagination — still zero credentials, still the public web preview, no Telethon involved.

**Confirmed live via `curl -A "Mozilla/5.0" https://t.me/s/telegram` (real public channel, not
guessed):**
- A preview page returns up to 20 `tgme_widget_message_wrap` blocks (`data-post="{channel}/{id}"`
  on each).
- Each page's "load more" link is `href="/s/{channel}?before={id}"` where `{id}` is the **lowest**
  message ID present on the *current* page — confirmed by fetching that exact URL next and
  observing it returns the next-older batch (IDs strictly below the cursor), with its own
  `before=` link pointing further back again.
- When a channel's history is exhausted, the page returns zero `tgme_widget_message_wrap` blocks
  (still HTTP 200 — not a 404) — this is the natural, observable stopping condition, not an
  inferred one.

**Scope decisions:**
- **Fixed page cap (`_MAX_PAGES = 10`, ~200 messages), not unbounded walk-to-genesis** — mirrors
  phase 12's Naver HTML fallback precedent (`_HTML_FALLBACK_MAX_PAGES = 3`) exactly: bounded,
  documented, stops early on an empty page, no attempt to fetch a channel's entire history in one
  run. 200 messages comfortably covers any realistic `--backfill` window for a source that's
  already being collected daily.
- **No date-aware early stop** — matches this codebase's existing convention (Naver/DART/SEC
  collectors all fetch a bounded set first, filter by date afterward, rather than threading a
  cutoff into the fetch loop itself). Consistency over a marginal request-count optimization.
- **Dedup by `message_id` across pages, not just concatenation** — defensive: if a cursor
  boundary is ever off-by-one (e.g. Telegram's own page includes an edge message twice across two
  requests), a `set` of seen IDs prevents a duplicate `CollectItem` rather than relying on the
  downstream `find_duplicate` dedup layer to paper over it.
- **A failure fetching a later page is NOT caught/degraded** — unlike the DART corp_code fetch or
  SEC companyfacts fetch (phases 15/16), a mid-pagination failure here isn't a "nice-to-have
  enrichment" that can be silently skipped; it's the core data being collected, so a real HTTP
  error while paginating should propagate and be handled by `_collect`'s existing per-item
  try/except → `CollectResult.errors`, same as any other collection failure.

## Task breakdown

### Task 1: Paginate `_fetch_all_messages`

**Files:** modify `investor_intel/collectors/telegram.py`; extend `tests/test_telegram.py`;
new fixture `tests/fixtures/telegram/channel_preview_empty.html` (a minimal, valid preview page
with zero `tgme_widget_message_wrap` blocks — the real "exhausted history" shape).

**Interfaces:** `TelegramCollector._fetch_all_messages` now loops (bounded by `_MAX_PAGES`):
fetch `self._source.url` for page 1, then `f"{self._source.url}?before={min_id}"` for subsequent
pages (`min_id` = the lowest numeric `message_id` parsed from the *previous* page), stopping when
a page yields zero not-yet-seen messages. Returns the deduplicated, concatenated list — no other
method's signature changes (`backfill`/`collect_incremental`/`_build_item`/`_collect` untouched).

- [ ] Write a failing test (the existing fixture's page returns 3 messages with IDs 101-103; mock
      `?before=101` to return the new empty fixture; assert pagination stops there and all 3
      original messages are still collected — i.e. update the existing `_mock_preview()` helper
      used by `test_backfill_returns_only_in_window_messages` and
      `test_collect_incremental_is_idempotent` to also mock the terminal empty page, since
      real-world behavior now includes that extra request); add a **new** test with a
      multi-page fixture (page 1 non-empty → page 2 non-empty with lower IDs → page 3 empty)
      asserting all messages across both non-empty pages are collected; add a test asserting the
      `_MAX_PAGES` cap is respected when no page ever returns empty (mirrors phase 12's
      `test_fetch_posts_via_html_stops_at_page_cap_without_empty_page`), implement, verify pass
- [ ] Commit: `feat: paginate Telegram public preview collection past the first page`

## Self-review notes

- **Verified against the live public preview, not guessed** — the `before=` cursor semantics
  (lowest ID on current page, not highest, not the "load more" button's own hidden state) were
  confirmed by literally following the link and observing the next page's ID range.
- **Reuses phase 12's exact bounded-pagination shape** — same cap-with-early-exit design,
  same "why not date-aware" reasoning — rather than inventing a new pattern for a structurally
  identical problem.
- **Existing tests updated for the new real behavior, not bypassed** — the extra `?before=`
  request now genuinely happens in production; the tests' mocks are extended to match reality
  (an empty terminal page) rather than the pagination logic being papered over with a try/except
  to keep old mocks passing unmodified.

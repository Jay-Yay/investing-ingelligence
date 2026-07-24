# Investor Essay Collector Implementation Plan

**Goal:** `InvestorConfig.related_essay_url` (`investor_intel/models/config.py`) has existed since
Core Foundation but nothing ever populates it into the vault — there is no collector for it. This
phase adds one. Scope, per the user's explicit correction: this is **not** a general essay
scraper — it collects the specific insight/analysis writing published by the investment entities
we already track via 13F (`investors.yaml`), when a `related_essay_url` is set for that investor
(e.g. Situational Awareness LP → `https://situational-awareness.ai/`, Leopold Aschenbrenner's
essay). Investors without one are simply skipped — most won't have one.

**Site research (verified live via `curl -A "Mozilla/5.0 ..."` against
`situational-awareness.ai`, not guessed):**
- `/feed/` returns a syntactically valid RSS channel with **zero** `<item>` entries — the essay is
  a WordPress *page*, not a *post*, and pages are excluded from the default feed. RSS is a dead end
  for this source; direct page scraping is the only option.
- The page itself is standard WordPress markup: `<h1 class="entry-title">SITUATIONAL AWARENESS:
  The Decade Ahead</h1>` and `<div class="entry-content">` wrapping the essay body as a sequence of
  `<p class="wp-block-paragraph">` tags.
- No reliable structured publish date anywhere on the page (no `article:published_time` meta, no
  visible dateline beyond a byline paragraph — "Leopold Aschenbrenner, June 2024" — that is prose,
  not a parseable timestamp).

**Scope decisions:**
- **No new dependency**, same as phase 12: stdlib `html.parser.HTMLParser`, matching
  `telegram_parser.py`/`naver_html_parser.py`.
- **One investor → one page, not a feed.** Unlike every other collector, there is no list to
  paginate — `related_essay_url` points directly at the one essay page. Each `backfill`/
  `collect_incremental` call fetches that single URL and yields at most one `CollectItem`.
  Idempotency across repeated runs is handled entirely by the existing shared machinery
  (`find_duplicate`'s canonical-url match + `write_document`'s content-hash skip in
  `storage/obsidian_repo.py`/`storage/sqlite_index.py`) — this collector does not need to
  reimplement dedup.
- **Extraction: WordPress-first with a generic fallback.** Try `entry-title`/`entry-content`
  first (covers the one confirmed real target); if a page has neither, fall back to the `<title>`
  tag for the title and every `<p>` on the page for the body. This keeps the door open for a
  future essay source that isn't WordPress without over-building for hypothetical layouts no real
  target uses yet.
- **`published_at` must be pinned, not re-derived every run — this is a correctness fix, not just
  a documented limitation.** The naive approach (`published_at = datetime.now(UTC)` on every
  collect) is actually a bug, not a cosmetic one: `path_for_document` embeds
  `{published_at:%Y}/{published_at:%Y-%m-%d}` in the file path
  (`storage/obsidian_repo.py:54-60`), so a fresh timestamp every run would make
  `persist_collect_result` write the essay to a *new* path each time (old file orphaned on disk)
  even though `find_duplicate` correctly resolves the same document `id` — silent duplicate-file
  accumulation. Fix: reuse `CheckpointStore`'s existing `last_seen_id` field (normally a natural
  post/message ID for other collectors) to instead persist the ISO timestamp of the *first*
  successful collection; every subsequent run reads it back and reuses it unchanged. This is an
  atypical use of that field (a timestamp instead of a natural ID) but avoids adding a new
  `CollectorState` column for a single collector's one-off need — `record_success`'s existing
  contract (only overwrites `last_seen_id` when a non-`None` value is explicitly passed) already
  supports "set once, read forever" with zero changes to `base.py`.
- **Language is hardcoded `"en"`** — mirroring how `naver_blog.py`/`telegram.py` hardcode `"ko"`
  for their known-Korean sources; the one confirmed real target is English-language, and no
  language-detection infra exists anywhere else in this codebase to justify adding one here.
- **`document_type="essay"`** (new value, alongside existing `"blog_post"`/`"opinion"` etc. —
  `SourceDocument.document_type` is a plain `str`, no enum to extend). `SourceType.ESSAY` and
  `_SOURCE_TYPE_DIR["essay"] = "Essays"` already exist in the codebase from Core Foundation
  (unused until now) — no model/storage changes needed, just wiring.

## Task breakdown

### Task 1: `collectors/essay_parser.py`

**Files:** create `investor_intel/collectors/essay_parser.py`; test
`tests/test_essay_parser.py`; fixtures `tests/fixtures/essay/wordpress_essay.html` (trimmed from
the real captured page — realistic `entry-title`/`entry-content`/`wp-block-paragraph` structure,
boilerplate stripped), `tests/fixtures/essay/generic_page.html` (a minimal non-WordPress page with
only a `<title>` and bare `<p>` tags, to exercise the fallback path).

**Interfaces:**
- `EssayPage` dataclass: `title: str`, `body_text: str`.
- `parse_essay_html(html_text: str) -> EssayPage` — tracks a generic open-tag stack (skipping void
  elements — `br`, `img`, `hr`, `meta`, `link`, etc. — so depth tracking isn't corrupted by
  unclosed tags); captures text within any element whose `class` includes `entry-title` as the
  title (falling back to `<title>` tag text if none found), captures every `<p>`'s text within an
  `entry-content`-classed element as the body (joined with blank lines), and — only when zero
  `entry-content` paragraphs were found — falls back to every `<p>` on the page outside
  `<script>`/`<style>`.

- [x] Write failing tests (WordPress fixture: exact title, a known paragraph substring, byline
      paragraph present in body; generic fixture: title from `<title>`, paragraph fallback
      triggers), implement, verify pass
- [x] Commit: `feat: add essay page HTML parser`

### Task 2: `collectors/essay_document.py` + `collectors/essay.py`

**Files:** create `investor_intel/collectors/essay_document.py` (renderer, mirrors
`dart_document.py`'s shape exactly: `ESSAY_LIMITATIONS_NOTE`, `render_essay_body`, header
`## 에세이 수집 시 유의사항`), create `investor_intel/collectors/essay.py` (`EssayCollector`
implementing the `Collector` protocol); tests `tests/test_essay_document.py`,
`tests/test_essay_collector.py`.

**Interfaces:**
- `EssayCollector(investor: InvestorConfig, client: SimpleHttpClient, checkpoint_store:
  CheckpointStore)` — `source_id = f"essay_{investor.id}"`; raises `ValueError` at construction if
  `investor.related_essay_url` is `None` (callers are expected to filter first, same as every
  other conditionally-wired collector in `pipeline/collect.py`).
- `backfill(days: int) -> CollectResult` and `collect_incremental() -> CollectResult` both delegate
  to one private `_collect()` — there's no "window" concept for a single fixed page, so `days` is
  accepted (protocol conformance) but unused; document this explicitly in the docstring/comment
  rather than silently ignoring it.
- `_collect()`: fetch the URL, `parse_essay_html`, resolve `published_at` from
  `checkpoint_store.get_state(source_id).last_seen_id` (parse as ISO datetime) or `datetime.now(UTC)`
  if unset, render the body, build one `CollectItem`, call
  `checkpoint_store.record_success(source_id, last_seen_id=published_at.isoformat())` (safe to
  call every time — a no-op rewrite once pinned), return a one-item `CollectResult`. On any
  exception: `record_failure`, return an empty/failed `CollectResult`.

- [x] Write failing tests: `essay_document` renders all 8 sections with the same header
      convention as every other source; `EssayCollector` — first `collect_incremental()` call
      sets `published_at` to "now" (`freeze_time`) and persists it via checkpoint; a second call
      one frozen-day later returns the **same** `published_at` (the pinning behavior — this is the
      test that would have caught the path-drift bug above); constructor raises `ValueError` when
      `related_essay_url` is `None`. Implement, verify pass.
- [x] Commit: `feat: add investor essay collector`

### Task 3: Wire into `build_collect_entries`

**Files:** modify `investor_intel/pipeline/collect.py`; extend the investors-loading branch's
test in `tests/test_pipeline_collect.py` (or wherever `build_collect_entries` is currently tested).

Inside the existing `investors_path.exists()` branch (`pipeline/collect.py:159-166`), after
constructing the `ThirteenFCollector` for each investor, additionally check
`investor.related_essay_url` — if set, construct an `EssayCollector` (reusing the same
`SimpleHttpClient` instance already created for `sources.yaml` collectors if available, or a fresh
one scoped to this branch — no SEC user-agent needed since this hits a public blog, not
`sec.gov`) and append `(essay_collector, SourceType.ESSAY, investor.id)` to `entries`.

- [x] Write a failing test (an `investors.yaml` fixture with one investor carrying
      `related_essay_url` and one without; assert exactly one `EssayCollector` entry appears,
      keyed to the investor *with* the URL), implement, verify pass
- [x] Commit: `feat: wire essay collector into collect pipeline`

## Self-review notes

- **The published_at-pinning fix is the load-bearing design decision in this phase** — it was
  originally going to be punted as a "documented limitation" (per prior planning), but tracing
  `path_for_document`'s actual behavior showed it's a genuine duplicate-file bug, not a cosmetic
  drift. Fixing it via `CheckpointStore.last_seen_id` reuse costs zero schema changes.
- **Reuse over reimplementation:** dedup/idempotency at the storage layer (`find_duplicate` +
  `write_document`'s content-hash skip) needed no changes — exactly the same shared path every
  other collector already relies on.
- **Matches established conventions exactly:** stdlib `HTMLParser` (no new dependency, per phase
  12's precedent), the 8-section renderer with a `{소스} 수집 시 유의사항` header (per every
  existing `*_document.py`), and the `Collector` protocol's `backfill`/`collect_incremental` shape.
- **Deliberately narrow, per explicit user correction:** this collects investor-authored
  insight/analysis, not arbitrary web essays — hence sourcing the URL from `InvestorConfig`
  (the 13F-tracked entity list), not a new standalone config file.

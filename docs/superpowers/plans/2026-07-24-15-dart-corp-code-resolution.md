# DART corpCode Auto-Resolution Implementation Plan

**Goal:** Phase 04 deliberately deferred this (`docs/superpowers/plans/2026-07-24-04-dart-collector.md`,
"Scope decision (corp_code)"): `KoreanCompanyConfig.corp_code` is currently a **required** field —
every entry in `dart_companies.yaml` must carry OpenDART's internal 8-digit `corp_code` by hand,
found by manually cross-referencing the entity in OpenDART's `corpCode.xml` master list. This
phase builds that lookup so `corp_code` becomes optional: supply a `ticker` (KRX 6-digit stock
code, e.g. `"005930"`) or `name`, and the collector resolves `corp_code` automatically the first
time it's needed, caching the result.

**Confirmed via reading the actual code (not assumed):**
- `KoreanCompanyConfig` (`models/config.py:27-31`): `ticker: str`, `corp_code: str` (required,
  no default), `name: str`, `report_types: list[str] = ["A", "B"]`.
- `DartClient` (`collectors/dart_client.py`) exposes only `get_json`/`close` — no method returns
  raw bytes, so it cannot fetch `corpCode.xml`'s ZIP body as-is. Needs a new `get_bytes` method.
- `storage/sqlite_index.py`'s `init_db` schema has exactly 3 tables (`documents`,
  `document_assets`, `collector_state`) — no place to cache a resolved mapping; a new table is
  needed. `reindex()` only touches `documents`/`document_assets` (rebuilding from the vault), and
  already leaves `collector_state` untouched across reindexes — the new cache table follows that
  same precedent (survives `reindex`, since it isn't vault-derived data).
- `build_collect_entries` (`pipeline/collect.py:152-207`) is called from exactly 2 places
  (`cli.py:390`, `pipeline/orchestrator.py:93`), and both already have a live `conn:
  sqlite3.Connection` in scope at the call site (they construct `CheckpointStore(conn)` from it
  immediately beforehand) — so passing `conn` through as a new explicit parameter, rather than
  reaching into `CheckpointStore`'s private `_conn`, costs only a 2-call-site signature update.
- OpenDART's real `corpCode.xml` endpoint:
  `https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={api_key}` — returns a ZIP file whose
  single member (`CORPCODE.xml`) contains `<result><list><corp_code>/<corp_name>/<stock_code>/
  <modify_date></list>...</result>` — one entry per registered corporate entity (tens of
  thousands; `stock_code` is empty/blank for entities with no listed stock).

**Scope decisions:**
- **Cache-if-empty, not staleness-tracked.** The full master list is large (tens of thousands of
  entries) and korean-listed companies' `corp_code`s essentially never change once assigned.
  Rather than building freshness/TTL tracking, the resolver fetches and caches the full list only
  when the local cache table is empty, or when a lookup misses (a ticker/name not found in the
  current cache — handles the case where a company IPO'd after the last cache population).
  Explicitly not handling: a company's `corp_code` changing after being cached (has never been
  observed to happen in practice) — a manual DB clear (`DELETE FROM dart_corp_codes`) forces a
  full re-resolution if ever needed; no CLI flag added for this since it's an edge case with a
  trivial manual escape hatch.
- **Resolution order: ticker (stock_code) first, exact name second.** Ticker match is
  unambiguous (KRX stock codes are unique); name is a fallback for unlisted entities that have no
  `stock_code` at all (matching phase 04's existing precedent of tracking KRX-listed companies,
  but not hard-restricting to only listed ones).
- **Config stays declarative when `corp_code` IS supplied** — `KoreanCompanyConfig.corp_code`
  becomes `str | None = None`; when set, it's used as-is with zero network calls, identical to
  today's behavior. Auto-resolution only activates for entries that omit it.
- **New SQLite table, not a new file/format** — reuses the existing regenerable-cache pattern
  already established by `collector_state` (also non-vault-derived, persisted alongside the
  document index, survives `reindex`).
- **Unresolvable entries become a `setup_errors` entry and are skipped**, mirroring the existing
  pattern for a missing `DART_API_KEY` (`pipeline/collect.py:189-192`) — not a hard crash of the
  whole `collect` run.

## Task breakdown

### Task 1: `collectors/dart_corp_code.py` — parsing + `DartClient.get_bytes`

**Files:** modify `investor_intel/collectors/dart_client.py` (add `get_bytes`); create
`investor_intel/collectors/dart_corp_code.py`; test `tests/test_dart_corp_code.py`; fixture
`tests/fixtures/dart/corp_code.zip` (a real ZIP, built from a small hand-authored
`CORPCODE.xml` — a handful of realistic entries including at least one with an empty
`<stock_code></stock_code>`, generated once via Python's `zipfile` module and checked in as
binary, OR built on-the-fly in a test fixture helper — prefer building it in a `conftest.py`/
fixture function at test time via `zipfile.ZipFile(io.BytesIO(), "w")` so there's no opaque
binary fixture to review, matching this repo's "text fixtures over binary" convention wherever
possible).

**Interfaces:**
- `CorpCodeEntry` dataclass: `corp_code: str`, `corp_name: str`, `stock_code: str | None` (empty
  string in the XML normalized to `None`), `modify_date: str`.
- `parse_corp_code_xml(xml_text: str) -> list[CorpCodeEntry]` — stdlib
  `xml.etree.ElementTree`, matching every other XML parser in this codebase
  (`naver_parser.py`/`thirteenf_parser.py`/`dart_filings_parser.py`).
- `unzip_corp_code_xml(zip_bytes: bytes) -> str` — stdlib `zipfile.ZipFile` +
  `io.BytesIO`, extracts and decodes the single member as UTF-8 (no new dependency).
- `DartClient.get_bytes(url: str) -> bytes` — reuses the existing `_request()` retry/rate-limit
  path, returns `.content` instead of `.json()`.

- [x] Write failing tests (`parse_corp_code_xml` on a multi-entry fixture, including one blank
      `stock_code`; `unzip_corp_code_xml` round-trips a ZIP built in the test itself;
      `DartClient.get_bytes` via `respx` returning binary content), implement, verify pass
- [x] Commit: `feat: add OpenDART corpCode.xml parser and DartClient byte fetch`

### Task 2: Cache table + resolver

**Files:** modify `investor_intel/storage/sqlite_index.py` (new `dart_corp_codes` table +
`replace_dart_corp_codes`/`find_dart_corp_code` functions); extend
`investor_intel/collectors/dart_corp_code.py` (add `resolve_corp_code`); tests
`tests/test_sqlite_index.py`, `tests/test_dart_corp_code.py`.

**Interfaces:**
- `dart_corp_codes` table: `corp_code TEXT PRIMARY KEY`, `corp_name TEXT NOT NULL`,
  `stock_code TEXT`, `modify_date TEXT`, plus `CREATE INDEX ... (stock_code)`.
- `replace_dart_corp_codes(conn, entries: list[CorpCodeEntry]) -> None` — `DELETE FROM
  dart_corp_codes` then bulk-insert, single commit (mirrors `reindex`'s delete-then-repopulate
  shape).
- `find_dart_corp_code(conn, *, stock_code: str | None, name: str | None) -> str | None` —
  `stock_code` exact match first, `corp_name` exact match second, `None` if neither hits.
- `is_dart_corp_code_cache_populated(conn) -> bool` — `SELECT COUNT(*) ...` != 0.
- `resolve_corp_code(conn, client: DartClient, api_key: str, *, ticker: str, name: str) ->
  str | None` — checks the cache first; on a miss (including an empty cache), fetches+unzips+
  parses+`replace_dart_corp_codes`, then retries the cache lookup once. Returns `None` if still
  unresolved after a fresh fetch (genuinely absent from OpenDART's master list).

- [x] Write failing tests (cold cache triggers exactly one fetch+populate+lookup cycle; warm
      cache resolves with zero network calls — assert via `respx` call count; a ticker absent
      even after a fresh fetch returns `None` without raising), implement, verify pass
- [x] Commit: `feat: cache and resolve DART corp_code by ticker or name`

### Task 3: Wire into config + `build_collect_entries`

**Files:** modify `investor_intel/models/config.py` (`corp_code: str | None = None`),
`investor_intel/pipeline/collect.py` (`build_collect_entries` gains a `conn` parameter; DART
branch resolves missing `corp_code`s before constructing `DartCollector`), `investor_intel/cli.py`
and `investor_intel/pipeline/orchestrator.py` (pass `conn` through, both already have it in
scope); extend `tests/test_build_collect_entries.py`.

- [x] Write a failing test (a `dart_companies.yaml` fixture with one entry that has `corp_code`
      set — zero network calls — and one that omits it and resolves via a mocked `corpCode.xml`
      response; a third entry with an unresolvable ticker produces a `setup_errors` message and
      is excluded from `entries`, not a crash), implement, verify pass
- [x] Commit: `feat: auto-resolve missing DART corp_code via cached corpCode.xml lookup`

## Self-review notes

- **Reuse over reimplementation:** parsing follows the same stdlib `ElementTree` convention as
  every other XML source in this codebase; the cache table follows `collector_state`'s existing
  "persists across reindex, not vault-derived" precedent instead of inventing a new persistence
  mechanism.
- **Deliberately narrow on staleness:** cache-if-empty-or-miss, no TTL/freshness tracking — matches
  phase 04's own stated bar ("may be added later if the config file becomes large enough") without
  over-building for a staleness scenario that has no observed real-world trigger.
- **`conn` threading is the one interface change with multiple call sites** — enumerated
  (`cli.py`, `orchestrator.py`) up front specifically so it doesn't get missed mid-implementation.

# SEC Company Filings Collector Implementation Plan

**Goal:** Build a SEC EDGAR company-filings collector that fetches 10-K/10-Q/8-K (domestic)
or 20-F/6-K (foreign private issuer) filing metadata for the three tracked companies (Nebius
Group NBIS, Bloom Energy BE, Reddit RDDT), producing `CollectItem`s that conform to the
`Collector` protocol built in the Core Foundation phase — same shape as the SEC 13F collector
(phase 02), reusing its HTTP client and URL-building utilities.

**Scope decision (MVP):** Unlike 13F informationTable XML (pure structured data), 10-K/10-Q/8-K
primary documents are large narrative HTML with no analogous "holdings" structure to parse in
this phase. This collector therefore captures filing **metadata only** (form type, filing date,
period of report, accession number, 8-K item codes, primary document description) plus a
canonical link — it does not fetch/parse the primary document's HTML body. `CollectItem.
content_capture_mode` is `"metadata_only"` with an explicit `content_capture_reason`. Full-text
capture and structured financial-statement extraction (XBRL) are explicitly out of scope for
this phase — a documented limitation, not an oversight; may be added in a later phase if the LLM
analysis pipeline (phase 07) needs full text.

**Tech stack:** reuses `httpx`/`respx`/`freezegun` (already project deps), no new dependencies.

## Global constraints

Inherited from Core Foundation and phase 02 (still binding):
- Python >= 3.12 via `uv`. No live network calls in tests — `respx` mocks all `httpx` traffic.
- `SEC_USER_AGENT` required; SEC EDGAR capped at 2 req/s.
- No placeholders/TODOs in shipped code.
- Collector does not read/write the Obsidian vault or SQLite index directly — only
  `CheckpointStore` (for incremental state) and returns `CollectResult`.

New constraints for this phase:
- Company identity/filing-type-per-company comes entirely from `CompanyConfig`
  (`investor_intel/models/config.py`, already exists): `ticker, cik, name, filing_types,
  is_foreign_private_issuer`. The collector filters to exactly `company.filing_types` — it does
  not hardcode form-type-by-FPI-status logic; config is the source of truth (matches
  `config/companies.yaml` scaffold already written in phase 01's `cli.py init`: NBIS →
  `[20-F, 6-K]`, BE/RDDT → `[10-K, 10-Q, 8-K]`).
- 8-K filings carry an `items` field in the EDGAR submissions feed (comma-separated event codes,
  e.g. `"2.02,9.01"`) — must be captured and rendered when present, since it's the only
  materiality signal available without parsing the body.

## Task breakdown

### Task 1: Shared SEC URL helpers (refactor)

**Files:** create `investor_intel/collectors/sec_urls.py`; modify `investor_intel/collectors/
sec_thirteenf.py` to import from it instead of defining its own private `_archive_dir` etc.

Extracts `cik_short`, `accession_nodashes`, `archive_dir`, `filing_index_url`,
`filing_index_page_url`, `document_url` (currently private, duplicated-in-spirit for the new
collector) into a shared, public module. Pure refactor — `tests/test_sec_thirteenf.py` must
still pass unmodified (its manual sanity check in phase 02's plan Task 7 already pins the exact
URL shape).

- [x] Extract functions into `sec_urls.py`, re-export/import from `sec_thirteenf.py`
- [x] Run full suite — all previously-passing tests (87) still green
- [x] Commit: `refactor: extract shared SEC EDGAR URL helpers into sec_urls.py`

### Task 2: Company filings parser

**Files:** create `investor_intel/collectors/sec_filings_parser.py`; fixture
`tests/fixtures/sec/submissions_company_test.json`; test `tests/test_sec_filings_parser.py`.

**Interfaces:**
- `CompanyFilingRef` (dataclass): `accession_number: str, filing_date: date,
  period_of_report: date | None, form: str, primary_document: str,
  primary_doc_description: str | None, items: list[str]`. Note `period_of_report` is optional
  here (unlike 13F's `FilingRef`) — 8-K's `reportDate` in the real EDGAR feed is sometimes blank
  for filings that predate its introduction; must not crash when missing/empty.
- `parse_company_filings(submissions: dict, forms: frozenset[str]) -> list[CompanyFilingRef]` —
  same recent-filings-array-of-parallel-lists shape as `thirteenf_parser.
  parse_submissions_filings`, plus reading the optional `items` array (comma-separated string
  per filing, split into a list; empty string → `[]`) and `primaryDocDescription` array.

- [x] Write failing tests: filters to configured forms only; parses 8-K `items` into a list;
      tolerates missing/blank `reportDate`; tolerates missing `items`/`primaryDocDescription`
      arrays entirely (some real submissions payloads omit them for older filings)
- [x] Implement
- [x] Run tests, verify pass
- [x] Commit: `feat: add SEC company filings submissions parser`

### Task 3: Company filing Markdown renderer

**Files:** create `investor_intel/collectors/sec_filings_document.py`; test
`tests/test_sec_filings_document.py`.

**Interfaces:**
- `SEC_FILING_LIMITATIONS_NOTE: str` — fixed disclosure: filing is a point-in-time regulatory
  disclosure, not investment advice; metadata-only capture (full text not fetched, see original
  link); 8-K item codes indicate topic, not materiality direction; foreign private issuer
  furnishes 6-K on a different cadence/content standard than domestic 8-K and the two are not
  directly comparable.
- `render_sec_filing_body(filing: CompanyFilingRef, company: CompanyConfig,
  canonical_url: str) -> str` — same 8-section Markdown shape as the 13F renderer (원문 /
  유의사항 / 핵심 주장 / 근거 / 반대 근거 / 언급 자산 / 포트폴리오 관련성 / 출처) for
  downstream consistency (the LLM extraction phase and daily-report renderer will look for the
  same section headers across all document types). "## 원문" body includes form type, filing
  date, period of report (or "해당 없음" if absent), accession number, and item codes for 8-K.

- [x] Write failing tests: all 8 sections present; limitations note verbatim present; 8-K item
      codes rendered when present; period-of-report absence renders without crashing
- [x] Implement
- [x] Run tests, verify pass
- [x] Commit: `feat: add SEC company filing Markdown renderer`

### Task 4: `SECFilingsCollector`

**Files:** create `investor_intel/collectors/sec_filings.py`; fixture
`tests/fixtures/sec/submissions_company_test.json` (from Task 2, reused); test
`tests/test_sec_filings.py`.

**Interfaces:**
- `SECFilingsCollector(company: CompanyConfig, client: SECClient,
  checkpoint_store: CheckpointStore)` with `.source_id = f"sec_filings_{company.ticker.lower()}"`,
  `.backfill(days: int) -> CollectResult`, `.collect_incremental() -> CollectResult` — conforms
  to the `Collector` protocol, same checkpoint/idempotency behavior as `ThirteenFCollector`
  (record last-seen accession on success; re-running incremental with no new filings yields
  `new_count == 0`).
- Forms filter is `frozenset(company.filing_types)` — no FPI branching in code.
- `CollectItem` per filing: `source_specific_id`/`accession_number` = accession number,
  `canonical_url` via `sec_urls.filing_index_page_url`, `title` = `f"{company.name} {form}
  ({period_of_report or filing_date})"`, `author` = company.name, `published_at` = filing_date
  (UTC midnight), `language` = `"en"`, `body_text` via Task 3's renderer, `content_capture_mode`
  = `"metadata_only"`, `content_capture_reason` set (see Task 3), `companies` = `[company.
  ticker]`, `document_type` = `"sec_filing"`, `filing_type` = form, `reporting_period` =
  `period_of_report.isoformat()` if present else `None`.
- One company per collector instance (mirrors `ThirteenFCollector` taking one investor) — the
  later orchestrator (phase 09) instantiates one per configured company, same as it will for
  13F/investors.

- [ ] Write failing tests: backfill respects day-window; collect_incremental first-run count and
      idempotent re-run; source_id includes lowercased ticker; a filing with a form not in
      `company.filing_types` is excluded even if present in the submissions feed
- [ ] Implement
- [ ] Run tests, verify pass
- [ ] Commit: `feat: add SECFilingsCollector for 10-K/10-Q/8-K/20-F/6-K metadata`

### Task 5: Full verification pass

- [ ] `uv run pytest -v` — all tests green (Core Foundation + phase 02 + phase 03)
- [ ] `uv run ruff check .` — clean
- [ ] `uv run mypy investor_intel` — clean
- [ ] Commit any fixes; update roadmap status for phase 03 to "merged to main"

## Self-review notes

- **No storage coupling:** `SECFilingsCollector` never imports `obsidian_repo` or
  `sqlite_index` for writing, matching phase 02's collector.
- **Reuse over duplication:** `SECClient`, `RateLimiter`, `CheckpointStore` are reused unchanged
  from Core Foundation/phase 02; URL-building is deduplicated into `sec_urls.py` rather than
  copy-pasted a second time.
- **Deferred, not skipped:** full-text capture and XBRL financial-statement extraction are
  named out-of-scope items for a future phase, not silently dropped.

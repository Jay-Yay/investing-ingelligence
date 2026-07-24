# SEC Financial-Statement Structured Extraction Implementation Plan

**Goal:** Every SEC filing captured today (`SECFilingsCollector`) is `content_capture_mode=
"metadata_only"` — form, dates, accession number, 8-K item codes — with zero actual financial
figures. This phase adds a dedicated, non-LLM structured extractor that pulls the handful of
headline financial-statement numbers (revenue, net income, total assets, total liabilities) for
each captured 10-K/10-Q directly from SEC's own structured XBRL data and appends them to the
document body as a new section — deterministic data, not an LLM-derived claim.

**Confirmed via reading the actual code AND live-fetching the real API (not assumed):**
- `SECFilingsCollector._build_item` (`sec_filings.py:37-67`) always sets
  `content_capture_mode="metadata_only"` with a fixed reason string
  (`"SEC filing HTML body is large and not parsed in this phase..."`). **This phase does not
  change that** — the reason refers to the narrative filing text (MD&A, footnotes, risk factors),
  which remains unparsed; only a handful of numeric XBRL facts are added, not full-text capture.
  Changing `content_capture_mode` to `"full"` would be inaccurate and isn't attempted.
- `pipeline/analyze.py` has **zero source-type branching** (confirmed — no `SourceType`/
  `source_type` references anywhere in that file). This extraction is **not** wired into
  `analyze_pending_documents` — it's deterministic data-fetching, not an LLM call, and belongs at
  **collection time** inside `SECFilingsCollector`, mirroring exactly how every other collector's
  `*_document.py` renderer builds the body at collect time (not analyze time).
- Real API, verified live via `curl -A "<UA>" https://data.sec.gov/api/xbrl/companyfacts/
  CIK0000320193.json` (Apple): returns `{"cik", "entityName", "facts": {"us-gaap": {<concept>:
  {"label", "units": {"USD": [{"start"?, "end", "val", "accn", "fy", "fp", "form", "filed",
  "frame"?}, ...]}}}}}`. One JSON payload per company covers **every historical fact across every
  filing** — not per-filing — so it must be fetched once per collector run and reused across all
  of that company's filings, not re-fetched per filing.
- **The same line item is tagged under different XBRL concept names across a company's own
  history** — confirmed live: Apple's "Revenues" tag (used through ~2018) and
  `RevenueFromContractWithCustomerExcludingAssessedTax` (used from ASC 606 adoption onward, 2018+)
  both exist in the *same* companyfacts payload for the *same* company. A single hardcoded
  concept name per line item is not sufficient — an ordered alias list per canonical line item is
  required.
- **Matching a fact to a specific filing is unambiguous via `accn` + `end` together, not `accn`
  alone** — a single accession number can carry multiple facts for the same concept (e.g. a 10-Q
  reporting both the current 3-month period and a prior comparison period under the same `accn`).
  `CompanyFilingRef.period_of_report` (already parsed by `sec_filings_parser.py:12`) gives the
  exact `end` date to match against, resolving the ambiguity exactly.
- `sec_urls.py` establishes the `data.sec.gov` URL convention already: full zero-padded CIK,
  no digit-stripping (unlike `Archives` URLs, which use `cik_short()`). The existing
  `_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"` in `sec_filings.py:12`
  is the precedent to match, not `archive_dir`'s stripped form.
- `tests/fixtures/sec/` has no companyfacts-shaped fixture — one will be hand-authored (small,
  realistic, JSON) rather than trimmed from a real capture (there's nothing to trim from in-repo).

**Scope decisions:**
- **Exactly 4 line items, not a general financial-statement model.** Revenue, net income, total
  assets, total liabilities — enough to give a claim-extraction LLM (and a human reader) real
  anchoring numbers without building a full income-statement/balance-sheet schema no one asked
  for. Each is independently optional (a filing may only resolve some, or none — 8-Ks typically
  resolve none, since they rarely carry structured financial-statement XBRL facts, which is an
  expected, non-error outcome, not a bug).
- **New optional section (`## 재무 데이터 (XBRL)`), not folded into `## 원문`.** Keeps the
  existing 8-section claims-splice contract (`pipeline/claims_splice.py`) completely untouched —
  `splice_claims_into_body` already preserves any unrecognized header verbatim, so adding a 9th,
  SEC-only section is safe by construction; verified by re-reading `_split_sections`'s generic
  loop rather than assuming compatibility.
- **Section omitted entirely when no line item resolves** (not rendered as an empty placeholder)
  — most 8-Ks will hit this path, and cluttering every 8-K with an empty "no data" section for
  something that fundamentally doesn't apply to that filing type would be noise, not signal.
- **Company-level companyfacts cache lives on `SECFilingsCollector` for the lifetime of one
  `backfill`/`collect_incremental` call** — fetched once, reused across every filing in that call.
  Not persisted to SQLite (unlike the DART corp_code cache in phase 15) — companyfacts changes
  whenever a company files anything new, so caching it across process runs would risk staleness
  for exactly the filings this feature cares about (recent ones); an in-memory, per-run cache is
  the right lifetime here, not a persistent one.
- **A companyfacts fetch failure (404 — no XBRL data on file, or a network error) degrades to "no
  snapshot for any filing this run," not a failed collection** — mirrors this project's
  established partial-failure-tolerance principle (a missing capability never crashes an
  unrelated, working one).

## Task breakdown

### Task 1: `collectors/sec_urls.py` + `collectors/sec_companyfacts.py` — fetch & parse

**Files:** modify `investor_intel/collectors/sec_urls.py` (add `companyfacts_url`); create
`investor_intel/collectors/sec_companyfacts.py`; test `tests/test_sec_companyfacts.py`; fixture
`tests/fixtures/sec/companyfacts_sample.json` (hand-authored, small — 2-3 concepts including at
least one with both an old and a new XBRL tag alias for the same line item, and multiple facts
sharing one `accn` to exercise the `end`-date disambiguation).

**Interfaces:**
- `companyfacts_url(cik: str) -> str` → `f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"`
  (full zero-padded CIK, matching the `_SUBMISSIONS_URL` convention, not `archive_dir`'s).
- `FinancialFact` dataclass: `concept: str`, `val: float`, `unit: str`, `start: date | None`,
  `end: date`, `accn: str`, `form: str`, `fy: int`, `fp: str`.
- `parse_companyfacts(data: dict, taxonomy: str = "us-gaap") -> dict[str, list[FinancialFact]]` —
  maps concept name → its `USD`-unit facts (skips concepts with no `USD` unit entirely; this
  covers the 4 target line items, which are always USD-denominated for US filers).
- `_CONCEPT_ALIASES: dict[str, list[str]]` — canonical name → ordered XBRL tag aliases, e.g.
  `"revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"]`,
  `"net_income": ["NetIncomeLoss"]`, `"total_assets": ["Assets"]`,
  `"total_liabilities": ["Liabilities"]`.
- `FinancialStatementSnapshot` dataclass: `revenue`, `net_income`, `total_assets`,
  `total_liabilities`, each `FinancialFact | None`.
- `extract_financial_snapshot(facts_by_concept: dict[str, list[FinancialFact]], *,
  accession_number: str, period_of_report: date | None) -> FinancialStatementSnapshot` — for each
  canonical item, tries its aliases in order, returns the first fact matching both `accn ==
  accession_number` and `end == period_of_report`; an item stays `None` if no alias/fact matches
  (including when `period_of_report` itself is `None` — some 8-Ks have no report date at all).

- [x] Write failing tests (`parse_companyfacts` on the fixture; `extract_financial_snapshot`
      correctly picks the ASC-606-era alias over the legacy one when both exist for the same
      company, correctly disambiguates two same-`accn` facts via `end` date, and returns an
      all-`None` snapshot for an accession number with no matching facts at all — the expected
      8-K case), implement, verify pass
- [x] Commit: `feat: add SEC XBRL companyfacts parser and financial snapshot extraction`

### Task 2: Wire into `SECFilingsCollector` + render section

**Files:** modify `investor_intel/collectors/sec_filings.py` (fetch companyfacts once per
run, pass the resolved snapshot into `_build_item`), `investor_intel/collectors/
sec_filings_document.py` (`render_sec_filing_body` gains an optional `snapshot` parameter, renders
`## 재무 데이터 (XBRL)` only when at least one field is set); extend `tests/test_sec_filings.py`,
create `tests/test_sec_filings_document.py` if it doesn't already cover this renderer (check
first — it may be covered inline in `test_sec_filings.py`).

**Interfaces:**
- `SECFilingsCollector._fetch_companyfacts() -> dict[str, list[FinancialFact]] | None` — calls
  `self._client.get_json(companyfacts_url(self._company.cik))` wrapped in `try/except Exception:
  return None` (404/network-error degradation), memoized for the collector instance's lifetime
  (fetched once at the top of `backfill`/`collect_incremental`, not per filing).
- `render_sec_filing_body(filing, company, canonical_url, snapshot: FinancialStatementSnapshot |
  None = None) -> str` — appends the new section (formatted as e.g. `"매출: $391,035,000,000
  (기간: 2024-09-28)"` per resolved field) right after `## 원문`, only when `snapshot` is not
  `None` and at least one field is set.

- [ ] Write a failing test (a filing whose accession number + period_of_report matches fixture
      facts renders the new section with the correct figures; an 8-K-shaped filing with no
      matching facts renders **without** the section at all — assert the header string is absent,
      not present-but-empty; a companyfacts fetch failure doesn't fail `backfill`/
      `collect_incremental`, just omits the section for every filing that run), implement, verify
      pass
- [ ] Commit: `feat: append structured financial-statement snapshot to SEC filing documents`

## Self-review notes

- **Verified against the live API, not assumed** — the concept-alias problem and the
  `accn`+`end` disambiguation requirement were both discovered by fetching Apple's real
  companyfacts payload during research, not by guessing XBRL's shape from documentation.
- **Deliberately not an LLM extraction step** — this is exact, deterministic SEC-sourced data;
  routing it through `extract_claims` would add non-determinism and cost to numbers that don't
  need either. Confirmed `analyze.py` has no per-source hook to begin with, so collection time is
  the only sensible integration point, not a retrofit.
- **Doesn't touch the claims-splice contract** — a 9th, always-preserved section, verified against
  `_split_sections`'s actual (generic, header-driven) logic rather than assumed compatible.
- **Narrow, correctly-scoped line-item set** — 4 headline figures, not a general financial model;
  matches this project's repeated pattern of "MVP scope, documented, not silently expanded."

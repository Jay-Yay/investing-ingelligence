# OpenDART Collector Implementation Plan

**Goal:** Build an OpenDART (Korean electronic disclosure system) collector for Korean tracked
companies, producing `CollectItem`s that conform to the `Collector` protocol — same shape and
scope decisions as the SEC filings collector (phase 03): metadata-only capture, no dependency on
downstream storage.

**Scope decision (MVP, mirrors phase 03):** OpenDART's 원문 API (`document.xml`) returns a ZIP
containing the filing's original XML — full-text extraction from that is out of scope for this
phase, same reasoning as 10-K/10-Q HTML in phase 03. This collector captures filing **metadata
only** (report name, receipt number, receipt date, filer name) plus a canonical DART viewer link.

**Scope decision (corp_code):** OpenDART's `corpCode.xml` endpoint returns a ZIP containing the
*entire* corp-code-to-company mapping (tens of thousands of entries) for dynamic ticker→corp_code
resolution. This phase does **not** build that lookup/cache subsystem — exactly as the SEC
collectors never dynamically resolve ticker→CIK, `corp_code` is supplied directly in
`dart_companies.yaml` (config is the source of truth, matching phase 01/02/03 precedent). A
`corp_code` cache may be added later if the config file becomes large enough that manual entry is
impractical; not needed for the (currently empty) Korean company list.

## Global constraints

Inherited from Core Foundation / phase 02 / phase 03 (still binding):
- Python >= 3.12 via `uv`. No live network calls in tests — `respx` mocks all `httpx` traffic.
- No placeholders/TODOs in shipped code.
- Collector does not read/write the Obsidian vault or SQLite index directly — only
  `CheckpointStore`, returns `CollectResult`.

New constraints for this phase:
- `DART_API_KEY` (already wired into `AppSettings.dart_api_key`) is required; a client
  constructed with an empty/missing key must raise, not silently send requests.
- OpenDART's `list.json` (공시검색) accepts exactly one `pblntf_ty` (공시유형) value per request,
  not a comma-separated set — a company tracking multiple report types (e.g. `["A", "B"]` =
  정기공시 + 주요사항보고) requires one API call per configured type, merged and deduplicated by
  `rcept_no` (접수번호, the stable per-filing identifier).
- `list.json` responses carry their own `status` field (`"000"` = success, `"013"` = no results
  for the query — not an error, must yield an empty list, not raise), independent of HTTP status.
  Any other status is a real API error and must raise.
- Rate limiting: conservative token-bucket via the existing `RateLimiter`
  (`investor_intel/collectors/base.py`), default 2 req/s (same conservative posture as SEC,
  matching the design doc's "소스별 보수적 값" guidance — DART's real quota is per-day, not
  per-second, so this is a safety margin rather than a hard vendor limit).

## Task breakdown

### Task 1: `KoreanCompanyConfig` model + loader

**Files:** modify `investor_intel/models/config.py`; modify `investor_intel/config/loaders.py`;
extend `tests/test_config_loaders.py`.

**Interfaces:**
- `KoreanCompanyConfig(BaseModel)`: `ticker: str` (KRX 종목코드), `corp_code: str` (DART 8-digit
  corp code), `name: str`, `report_types: list[str] = ["A", "B"]` (DART `pblntf_ty` codes).
- `load_dart_companies_yaml(path: Path) -> list[KoreanCompanyConfig]` reading a new
  `dart_companies.yaml` (top-level key `dart_companies`), same pattern as
  `load_companies_yaml`. No entries need to exist yet in `cli.py`'s scaffold — Korean company
  list stays empty until the user supplies it (matches design doc §5, a documented non-blocking
  item).

- [x] Write failing tests, implement, verify pass
- [x] Commit: `feat: add KoreanCompanyConfig model and dart_companies.yaml loader`

### Task 2: DART HTTP client

**Files:** create `investor_intel/collectors/dart_client.py`; test `tests/test_dart_client.py`.

**Interfaces:**
- `DartClientError(Exception)`.
- `DartClient(api_key: str, rate_limiter=None, http_client: httpx.Client | None = None)` with
  `.get_json(url: str) -> dict`, `.close() -> None`. Same retry-on-{429,500,502,503,504} + backoff
  shape as `SECClient` (phase 02) — `crtfc_key` is a query param baked into each request URL by
  the caller, not a header, so the client itself needs no special header logic beyond a sane
  default `User-Agent`/timeout.
- Empty/missing `api_key` raises `ValueError` at construction.

- [x] Write failing tests (empty key raises; retries transient 5xx/429; persistent failure raises
      `DartClientError`; rate limiter `.acquire()` called per request), implement, verify pass
- [x] Commit: `feat: add rate-limited retrying OpenDART HTTP client`

### Task 3: DART filings list parser

**Files:** create `investor_intel/collectors/dart_filings_parser.py`; fixtures
`tests/fixtures/dart/list_success.json`, `tests/fixtures/dart/list_no_data.json`,
`tests/fixtures/dart/list_error.json`; test `tests/test_dart_filings_parser.py`.

**Interfaces:**
- `DartFilingRef` (dataclass): `rcept_no: str, rcept_dt: date, report_nm: str, corp_name: str,
  corp_code: str, flr_nm: str, corp_cls: str`.
- `DartAPIError(Exception)`.
- `parse_dart_list_response(response: dict) -> list[DartFilingRef]` — returns `[]` on status
  `"013"`; raises `DartAPIError` on any status other than `"000"`/`"013"`; parses `rcept_dt`
  (`YYYYMMDD` string, no dashes) into a `date`.

- [ ] Write failing tests (success parses all fields incl. `rcept_dt` format; `"013"` → `[]`, no
      raise; other error status raises `DartAPIError` with the message included), implement,
      verify pass
- [ ] Commit: `feat: add OpenDART list.json response parser`

### Task 4: DART Markdown renderer

**Files:** create `investor_intel/collectors/dart_document.py`; test
`tests/test_dart_document.py`.

**Interfaces:**
- `DART_LIMITATIONS_NOTE: str` — fixed disclosure: DART 공시는 특정 시점의 규제 공시이며 투자
  자문이 아님; 원문 XML은 이 단계에서 수집하지 않고 메타데이터와 뷰어 링크만 캡처함; 정정/정정보고서가
  있을 수 있으며 이 컬렉터는 최초 접수 건과 정정 건을 동일하게 개별 문서로 취급함(자동 병합하지
  않음).
- `render_dart_filing_body(filing: DartFilingRef, canonical_url: str) -> str` — same 8-section
  Markdown shape as phases 02/03's renderers (원문 / 유의사항 / 핵심 주장 / 근거 / 반대 근거 /
  언급 자산 / 포트폴리오 관련성 / 출처) for cross-source consistency.

- [ ] Write failing tests (all 8 sections present; limitations note verbatim; report name/receipt
      number/date/filer name present), implement, verify pass
- [ ] Commit: `feat: add OpenDART filing Markdown renderer`

### Task 5: `DartCollector`

**Files:** create `investor_intel/collectors/dart.py`; fixtures as needed; test
`tests/test_dart_collector.py`.

**Interfaces:**
- `DartCollector(company: KoreanCompanyConfig, client: DartClient,
  checkpoint_store: CheckpointStore, api_key: str)` with `.source_id = f"dart_{company.ticker}"`,
  `.backfill(days: int) -> CollectResult`, `.collect_incremental() -> CollectResult` — conforms to
  `Collector`.
- Canonical URL: `https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}`.
- Issues one `list.json` call per configured `report_types` entry (per the global constraint
  above), `bgn_de`/`end_de` as `YYYYMMDD`, merges + dedupes by `rcept_no`, sorts by `rcept_dt`.
- `CollectItem`: `source_specific_id` = `rcept_no`, `language` = `"ko"`, `content_capture_mode`
  = `"metadata_only"` (+ reason), `document_type` = `"dart_filing"`, `filing_type` =
  `report_nm`, `reporting_period` = `rcept_dt.isoformat()`, `accession_number` = `rcept_no`,
  `companies` = `[company.ticker]`.
- Same checkpoint/idempotency contract as `ThirteenFCollector`/`SECFilingsCollector`: incremental
  re-run with nothing new → `new_count == 0`.

- [ ] Write failing tests (backfill day-window; incremental idempotency; multi-report-type merge
      dedupes overlapping `rcept_no` across two `pblntf_ty` calls; `"013"` no-data response
      yields zero items without error), implement, verify pass
- [ ] Commit: `feat: add DartCollector for OpenDART Korean filings metadata`

### Task 6: Full verification pass

- [ ] `uv run pytest -v` — all tests green
- [ ] `uv run ruff check .` — clean
- [ ] `uv run mypy investor_intel` — clean
- [ ] Commit any fixes; update roadmap status for phase 04 to "merged to main"

## Self-review notes

- **No storage coupling:** `DartCollector` never imports `obsidian_repo`/`sqlite_index` for
  writing.
- **Consistency with phases 02/03:** same `Collector` protocol, same `CollectResult`/checkpoint
  idempotency contract, same 8-section Markdown renderer shape, same metadata-only scope
  decision for large original documents.
- **Deferred, not skipped:** `corp_code` auto-resolution (corpCode.xml caching) and full 원문 XML
  capture are named out-of-scope items, not silently dropped.

# Reports, Full CLI, Orchestrator Implementation Plan

**Goal:** Wire every subsystem built in phases 01-08 into an actual runnable pipeline: collect →
persist → analyze → portfolio → report, plus the CLI commands and scheduled-run scaffold to
drive it. This is the integration phase — little new business logic, mostly composition.

**Scope decisions:**
- **No essay collector.** `SourceType.ESSAY` exists in `models/common.py` but no essay collector
  was ever scoped on the roadmap (phases 01-08 cover 13F/SEC-filings/DART/Naver/Telegram only).
  Not built here either — the collector registry below covers exactly the 5 collectors that
  exist.
- **`llm/daily_report.py` is a thin one-shot synthesis call**, not a conversation — it takes the
  day's structured summary (new documents, portfolio metrics, guardrail violations) and asks
  Claude for Korean prose framing, same `AnthropicClient` DI pattern as `extraction.py` but no
  tool-use/retry (free-text output, nothing to JSON-validate).
- **Recommendation cap, not recommendation generation, still holds from phase 08.**
  `llm/portfolio_impact.py` combines an LLM-suggested `RecommendationRating` (produced elsewhere,
  or supplied directly by the orchestrator from extracted claims' `direction`/`confidence` as a
  simple heuristic — see Task 3) with phase 08's `max_allowed_recommendation` cap. It does not
  reimplement claim-to-rating synthesis as a separate LLM call; that would duplicate
  `extraction.py`'s output for no benefit at this scope.
- **Partial-failure tolerance (§14 of the design doc):** the orchestrator collects a
  per-source/per-stage error list and keeps going — one collector's failure (bad credentials, a
  network blip) must not abort the whole run. Matches every collector's own
  `CollectResult(success, items, errors)` contract already built in phases 02-05.
- **New dependency:** `jinja2` (already chosen in the design doc's tech-stack table) for the
  daily report template — added here since this is the first phase that actually renders one.

## Global constraints

Inherited from phases 01-08: no placeholders/TODOs; no live network calls in tests (collectors
are mocked at the `Collector` protocol boundary here, not re-mocked at the HTTP layer — that's
already covered by each collector's own test suite).

## Task breakdown

### Task 1: `pipeline/collect.py`

**Files:** create `investor_intel/pipeline/__init__.py` (empty),
`investor_intel/pipeline/collect.py`; test `tests/test_pipeline_collect.py`.

**Interfaces:** `collect_item_to_source_document(item: CollectItem, source_type: SourceType,
source_name: str) -> tuple[SourceDocument, str]` — pure conversion; `id` via
`content_hash.compute_stable_id`, `content_hash` via `compute_content_hash(item.body_text)`;
returns `(doc, item.body_text)` for the caller to write. `persist_collect_result(result:
CollectResult, source_type: SourceType, source_name: str, vault_path: Path, conn:
sqlite3.Connection) -> PersistResult` (`PersistResult(count: int, errors: list[str])`) — for
each item: resolve the real `id` via `sqlite_index.find_duplicate` (§10 5-step dedup, already
implemented — reused, not reimplemented) falling back to the freshly computed stable id when no
match is found, then `obsidian_repo.write_document` (already idempotent on unchanged
content_hash) + `sqlite_index.upsert_document`. Never raises on a single item's
conversion/write failure — appends to `errors` and continues, same style as `CollectResult`.

- [x] Write failing tests (conversion produces a valid `SourceDocument` whose `content_capture`
      satisfies the existing mode/reason validator for both `full` and `metadata_only` items;
      persisting the same item twice is idempotent — second call doesn't create a duplicate
      vault file; a duplicate detected by `find_duplicate` reuses the existing id), implement,
      verify pass
- [x] Commit: `feat: add collect-result persistence pipeline (CollectItem to vault+index)`

### Task 2: CLI `collect` command

**Files:** modify `investor_intel/cli.py`; test `tests/test_cli_collect.py`.

**Interfaces:** `@app.command() def collect(...)` — loads `investors.yaml`, `companies.yaml`,
`dart_companies.yaml`, `sources.yaml` from `--config-dir`; for each enabled entry, builds the
matching collector (`ThirteenFCollector`/`SECFilingsCollector`/`DartCollector`/
`NaverBlogCollector`/`TelegramCollector`) using `AppSettings` for credentials
(`sec_user_agent`/`dart_api_key`) and a shared `CheckpointStore`; runs `.collect_incremental()`
(or `.backfill(days)` when `--backfill N` is passed); persists via Task 1; prints a per-source
summary line and a nonzero exit code if any source errored (still runs every other source first
— partial-failure tolerance applies here too, not just in the orchestrator).

- [x] Write failing tests (a fake in-memory `Collector` wired through the real persistence path
      confirms end-to-end vault+index writes; a failing collector doesn't stop the others from
      running), implement, verify pass
- [x] Commit: `feat: add CLI collect command wiring all five collectors`

### Task 3: Portfolio impact recommendation cap

**Files:** create `investor_intel/llm/portfolio_impact.py`; test
`tests/test_llm_portfolio_impact.py`.

**Interfaces:** `RATING_ORDER: list[RecommendationRating]` (SELL → REDUCE → HOLD → BUY →
STRONG_BUY, least to most bullish). `suggest_rating_from_claims(claims: list[Claim]) ->
RecommendationRating` — a simple, documented heuristic (not an LLM call): majority
`direction` vote among `HIGH`/`MEDIUM` confidence claims maps `BULLISH → BUY`, `BEARISH →
REDUCE`, `NEUTRAL`/no-claims/tie → `HOLD`. `apply_recommendation_cap(suggested:
RecommendationRating, cap: RecommendationRating | None) -> RecommendationRating` — returns
whichever of `suggested`/`cap` is less bullish per `RATING_ORDER`, or `suggested` unchanged when
`cap` is `None`.

- [ ] Write failing tests (heuristic picks majority direction; ties/no claims → `HOLD`; cap
      pulls a `STRONG_BUY` suggestion down to `HOLD`; `None` cap is a no-op), implement, verify
      pass
- [ ] Commit: `feat: add portfolio-impact recommendation heuristic and guardrail cap`

### Task 4: Daily report renderer

**Files:** modify `pyproject.toml` (add `jinja2` via `uv add`); create
`investor_intel/reports/__init__.py` (empty),
`investor_intel/reports/daily_report_renderer.py`; test `tests/test_daily_report_renderer.py`.

**Interfaces:** `DailyReportContext(BaseModel)`: `report_date: date, narrative: str,
new_documents: list[dict], position_rows: list[dict], guardrail_violations:
list[GuardrailViolation]` — a plain data container the renderer consumes (fields are the exact
shape the Jinja2 template iterates; the orchestrator in Task 6 is what actually assembles one
from real pipeline state). `render_daily_report(context: DailyReportContext) -> str` — Markdown
via an inline Jinja2 template (small enough not to need a separate `.j2` file): title, the LLM
`narrative`, a new-documents table, a portfolio positions table, a guardrail-violations section
(omitted when empty).

- [ ] Write failing tests (renders all sections; omits the violations section when the list is
      empty; new-documents/position rows appear in the output), implement, verify pass
- [ ] Commit: `feat: add daily report Jinja2 renderer`

### Task 5: LLM daily report synthesis

**Files:** create `investor_intel/llm/daily_report.py`; test
`tests/test_llm_daily_report.py`.

**Interfaces:** `synthesize_daily_narrative(client: AnthropicClient, summary: str, system_prompt:
str) -> str` — one `client.create_message` call (no tools, no retry), returns the first `text`
content block. Raises `ExtractionError`-style... no — a new, distinct `DailyReportError(Exception)`
if the response has no text block (keeps error types scoped to the module that raises them,
not shared with `extraction.py`'s unrelated failure mode).

- [ ] Write failing tests (returns the text block content; raises when no text block present),
      implement, verify pass
- [ ] Commit: `feat: add LLM daily report narrative synthesis`

### Task 6: Orchestrator + remaining CLI commands

**Files:** create `investor_intel/pipeline/orchestrator.py`; modify `investor_intel/cli.py`;
test `tests/test_orchestrator.py`.

**Interfaces:** `run_daily(config_dir: Path, vault_path: Path, sqlite_path: Path, settings:
AppSettings) -> RunDailyResult` (`RunDailyResult(BaseModel)`: `collect_errors: list[str],
analyze_errors: list[str], report_path: str | None, success: bool`) — runs collect (Task 2's
logic, factored to be callable without going through Typer) for every configured source, then
analyze (LLM extraction over `llm_processed=false` documents, cost-budget aware via
`CostTracker.is_within_budget`, stopping analysis but not the run when the budget is hit — per
§3.4), then portfolio calculations + guardrails (phase 08) using `MarketDataProvider` prices,
then the daily report (Tasks 3-5), writing the result to
`{vault_path}/50_Reports/Daily/{date}.md`. Never raises on a single source/document failure;
`success` reflects whether the report was ultimately produced. CLI: `analyze`, `portfolio`,
`report` (each runs one stage standalone, for manual/debugging use) and `run-daily` (the full
pipeline) commands, all following the existing `--vault-path`/`--config-dir`/`--sqlite-path`
option conventions from `init`/`doctor`/`reindex`.

- [ ] Write failing tests (a fully-mocked run — fake collectors, fake LLM client, fake market
      data — produces a report file and a `success=True` result; a collector failure is recorded
      in `collect_errors` but the run still reaches the report stage; budget-exhausted skips
      remaining analysis but still produces a report from what was analyzed), implement, verify
      pass
- [ ] Commit: `feat: add run-daily orchestrator and remaining CLI commands`

### Task 7: Cron / GitHub Actions scaffold

**Files:** create `.github/workflows/daily-collect.yml`; modify
`vault/00_System/Runbook.md`'s scaffold text in `cli.py` (or add a `CRON.md` note) — cron/GH
Actions is configuration, not code with its own test suite; verify by `yaml.safe_load`-ing the
workflow file in a one-off check rather than a permanent pytest (no runtime behavior to unit
test in a static schedule file).

- [ ] Write the workflow file (scheduled `cron`, `workflow_dispatch` for manual runs, checks out
      the repo, sets up `uv`, runs `uv run investor-intel run-daily`, referencing repo secrets
      for the `.env` values already named in `cli.py`'s `ENV_EXAMPLE`)
- [ ] Sanity-check: `python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/daily-collect.yml'))"`
- [ ] Commit: `feat: add scheduled GitHub Actions workflow for run-daily`

### Task 8: Full verification pass

- [ ] `uv run pytest -v` — all tests green
- [ ] `uv run ruff check .` — clean
- [ ] `uv run mypy investor_intel` — clean
- [ ] Commit any fixes; update roadmap status for phase 09 to "merged to main"

## Self-review notes

- **Partial failure is load-bearing, not decorative:** every stage's test explicitly verifies
  that one failure doesn't halt the run, matching §14.
- **Reuse over reimplementation:** dedup, checkpointing, cost budgeting, and guardrail capping
  all reuse phases 01-08's functions verbatim — this phase is composition.
- **Deferred, not skipped:** an essay collector and true LLM-driven (vs. heuristic) portfolio
  recommendation synthesis are named out-of-scope items with stated reasons.

# LLM Pipeline Implementation Plan

**Goal:** Build the Anthropic client wrapper, structured claim extraction, and LLM cost tracking
— the three items the roadmap assigns to phase 07 (`llm/portfolio_impact.py` and
`llm/daily_report.py` are deferred to phases 08/09, which is where the portfolio and report
models they depend on actually get built).

**Scope decision (SDK, not raw HTTP):** Unlike every collector so far (hand-rolled `httpx`
clients), this phase depends on the official `anthropic` Python SDK — it's the correct tool for
calling Claude (typed request/response models, retry handling, tool-use support) and reinventing
it would just be worse-tested raw HTTP. Tests inject a fake object implementing only
`.messages.create(...)` (duck-typed to the bits `extraction.py`/`client.py` actually touch) —
no real network calls, no `respx` needed since the SDK's transport isn't httpx-shaped the way
`respx` mocks.

**Scope decision (cost tracker persistence):** A new `storage/cost_ledger.py` (plain `sqlite3`,
same pattern as `sqlite_index.py`) persists per-call token usage; `llm/cost_tracker.py` layers
pricing + budget-check logic on top — mirrors how `CheckpointStore` wraps `sqlite_index.py`'s
collector-state functions.

**Pricing table (verified 2026-07-24 via the project's Claude API pricing reference, standard
rates not the temporary intro discount that expires 2026-08-31):** `claude-sonnet-5` input
$3.00 / output $15.00 per million tokens; `claude-opus-4-8` $5.00 / $25.00; `claude-haiku-4-5`
$1.00 / $5.00. `ANTHROPIC_MODEL` (already in `AppSettings`, default `claude-sonnet-5`) must
resolve to one of these — an unpriced model raises rather than silently costing `$0`.

## Global constraints

Inherited from phases 01-06: no placeholders/TODOs; no live network calls in tests.

New for this phase:
- `ANTHROPIC_MODEL` env var drives which model string is used — never hardcode a model id
  outside `AppSettings`/the pricing table lookup (the pricing table's keys are the one place
  model ids necessarily appear as literals, since pricing genuinely differs per model).
- Extraction must wrap the raw document body with `security/untrusted_content`'s existing
  delimiting utility (Core Foundation phase) before it reaches the LLM — the prompt-injection
  defense already built must actually be wired in here, not just exist unused.
- On tool-use JSON validation failure, retry up to 2 more times (3 attempts total) before
  raising — matches the design doc's stated behavior (§3.4: caller marks the document
  `llm_processed:false` and retries on the next run; that's the orchestrator's job in phase 09,
  not this phase's).

## Task breakdown

### Task 1: Anthropic client wrapper

**Files:** modify `pyproject.toml` (add `anthropic` runtime dep via `uv add`); create
`investor_intel/llm/__init__.py` (empty), `investor_intel/llm/client.py`; test
`tests/test_llm_client.py`.

**Interfaces:** `AnthropicClient(api_key: str, model: str, client: anthropic.Anthropic | None =
None)` — raises `ValueError` on empty `api_key`. `.create_message(*, system: str, messages:
list[dict], tools: list[dict] | None = None, tool_choice: dict | None = None, max_tokens: int =
4096)` — thin passthrough to `self._client.messages.create(...)`, returning the raw SDK response
object (no reinvented types). `.model` property exposes the configured model string (so callers/
cost tracker never need a second source of truth for which model was used).

- [ ] Write failing tests (empty api_key raises; `create_message` forwards args to the injected
      fake client and returns its result; `.model` reflects the constructor arg), implement,
      verify pass
- [ ] Commit: `feat: add Anthropic client wrapper`

### Task 2: Cost ledger + cost tracker

**Files:** create `investor_intel/storage/cost_ledger.py`; test
`tests/test_cost_ledger.py`. Create `investor_intel/llm/cost_tracker.py`; test
`tests/test_cost_tracker.py`.

**Interfaces:**
- `storage/cost_ledger.py`: `init_cost_ledger(conn) -> None` (creates `llm_usage` table);
  `record_usage(conn, timestamp: datetime, model: str, input_tokens: int, output_tokens: int,
  cost_usd: float) -> None`; `sum_cost_between(conn, start: datetime, end: datetime) -> float`.
- `llm/cost_tracker.py`: `UnknownModelPricingError(Exception)`; `compute_cost_usd(model: str,
  input_tokens: int, output_tokens: int) -> float` (raises on unpriced model — see pricing table
  above); `CostTracker(conn, daily_budget_usd: float, monthly_budget_usd: float, timezone: str =
  "Asia/Seoul")` with `.record_usage(model, input_tokens, output_tokens) -> float` (computes +
  persists + returns cost), `.daily_total_usd() -> float` / `.monthly_total_usd() -> float`
  (day/month boundaries computed in the configured timezone — a "daily" budget means the
  project's Asia/Seoul day, not a UTC day), `.is_within_budget() -> bool`.

- [ ] Write failing tests (compute_cost_usd known-model arithmetic + unpriced-model raise;
      ledger round-trip; `CostTracker.record_usage` persists and returns matching cost;
      `daily_total_usd`/`monthly_total_usd` sum correctly across a KST day/month boundary via
      `freeze_time`; `is_within_budget` true under budget, false at/over), implement, verify pass
- [ ] Commit: `feat: add LLM cost ledger and budget-aware cost tracker`

### Task 3: `Claim`/`ExtractionResult` models

**Files:** create `investor_intel/models/analysis.py`; test `tests/test_models_analysis.py`.

**Interfaces:** `Claim(BaseModel)`: `claim: str, evidence: list[str], counter_evidence:
list[str] = [], assets: list[str] = [], fact_or_opinion: FactOrOpinion, direction: Direction,
confidence: ConfidenceLevel` — field set and enum types match `investor_intel/cli.py`'s
`extract_claims.md` prompt spec and the enums already defined in `models/common.py` (Core
Foundation phase — reused here, not redefined). `ExtractionResult(BaseModel)`: `claims:
list[Claim]`.

- [ ] Write failing tests (valid construction; enum fields reject invalid values), implement,
      verify pass
- [ ] Commit: `feat: add Claim and ExtractionResult models`

### Task 4: Structured extraction pipeline

**Files:** create `investor_intel/llm/extraction.py`; test `tests/test_llm_extraction.py`.

**Interfaces:** `ExtractionError(Exception)`. `EXTRACTION_TOOL_SCHEMA: dict` (tool-use schema
whose `input_schema` mirrors `ExtractionResult`'s shape). `extract_claims(client:
AnthropicClient, document_body: str, system_prompt: str, max_retries: int = 2) ->
ExtractionResult` — wraps `document_body` with `security.untrusted_content`'s existing wrapper
before sending; forces the tool call via `tool_choice`; validates the returned `tool_use` block's
`input` against `ExtractionResult`; on missing tool-use block or a `pydantic.ValidationError`,
retries (same wrapped content, fresh call) up to `max_retries` more times; raises
`ExtractionError` after exhausting retries.

- [ ] Write failing tests (happy path returns a validated `ExtractionResult`; a fake client
      returning invalid `tool_use.input` on attempt 1 and valid on attempt 2 succeeds via retry;
      exhausting all retries raises `ExtractionError`; the untrusted-content wrapper's markers
      are present in the `messages` payload sent to the client — proves the injection defense is
      actually wired in, not just imported), implement, verify pass
- [ ] Commit: `feat: add structured claim extraction with tool-use and retry`

### Task 5: Full verification pass

- [ ] `uv run pytest -v` — all tests green
- [ ] `uv run ruff check .` — clean
- [ ] `uv run mypy investor_intel` — clean
- [ ] Commit any fixes; update roadmap status for phase 07 to "merged to main"

## Self-review notes

- **No storage coupling beyond the cost ledger:** `extraction.py` never touches
  `obsidian_repo`/`sqlite_index` — turning an `ExtractionResult` into vault frontmatter updates
  is the orchestrator's job (phase 09), matching the design doc's data-flow diagram.
- **Deferred, not skipped:** `llm/portfolio_impact.py` and `llm/daily_report.py` need models
  that don't exist until phases 08/09; named here as explicitly out of scope for phase 07, not
  forgotten.
- **Reuse over duplication:** `security/untrusted_content.py` (Core Foundation) and
  `models/common.py`'s enums are reused as-is, not reimplemented.

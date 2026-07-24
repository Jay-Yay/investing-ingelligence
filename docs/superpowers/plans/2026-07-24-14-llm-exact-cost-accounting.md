# LLM Exact Token-Usage Cost Accounting Implementation Plan

**Goal:** `analyze_pending_documents` (`investor_intel/pipeline/analyze.py:51-52`) currently
estimates token counts from character length (`(len(body) + len(system_prompt)) // 4` for input,
`len(json.dumps(extraction.model_dump())) // 4` for output) instead of using the real numbers the
Anthropic API already returns on every response. This phase switches to real usage.

**Confirmed via reading the actual code (not assumed):**
- `AnthropicClient.create_message()` (`llm/client.py:28`) returns the SDK's `Message` object
  verbatim — un-wrapped, nothing discards `.usage`.
- `extract_claims()` (`llm/extraction.py:52-83`) already holds that `response` locally on every
  loop iteration (including retried/failed attempts) but only ever returns the parsed
  `ExtractionResult` — the real `response.usage.input_tokens`/`.output_tokens` is computed by the
  API and then thrown away.
- `CostTracker.record_usage(model, input_tokens, output_tokens)` (`llm/cost_tracker.py:40`)
  already accepts raw token counts from any source — **no change needed there**, this is purely
  about what `analyze.py` passes in.
- `extract_claims` has exactly one production call site (`pipeline/analyze.py:49`) and is
  exercised in `tests/test_llm_extraction.py` (5 tests) and `tests/test_pipeline_analyze.py` (3
  tests) — a fully enumerable set of call sites to update.

**Scope decisions:**
- **Every retry attempt consumes real, billable tokens** — `extract_claims`'s retry loop
  (`max_retries=2` by default) can call `create_message` up to 3 times before giving up or
  succeeding. Usage must be **summed across every attempt in that call**, not just the last/
  successful one, or a validation-failure retry would silently undercount real spend.
- **On total failure (`ExtractionError` raised after exhausting retries), no cost is recorded —
  this is a pre-existing gap, not something this phase fixes.** `analyze_pending_documents`
  already wraps the whole per-document block in `try/except Exception: errors.append(...)` with
  no cost-recording path on that branch, true before and after this change. Documenting it here
  rather than silently expanding scope to fix it — the failed attempts' tokens were never
  recorded even under the old estimate-based system either (the estimate itself was computed only
  after a successful return).
- **`extract_claims`'s return type changes** from bare `ExtractionResult` to a small
  `ExtractionOutcome(result: ExtractionResult, usage: TokenUsage)` wrapper (`TokenUsage(
  input_tokens: int, output_tokens: int)`, both new dataclasses in `llm/extraction.py`). This is a
  deliberate breaking change to `extract_claims`'s public shape — accepted because the call site
  count is small and enumerated above, and there's no other way to surface real usage without it
  (the alternative — a mutable out-parameter or a module-level "last usage" global — is worse).

## Task breakdown

### Task 1: Return usage from `extract_claims`

**Files:** modify `investor_intel/llm/extraction.py`; extend `tests/test_llm_extraction.py`.

Add `TokenUsage`/`ExtractionOutcome` dataclasses. Accumulate `response.usage.input_tokens`/
`.output_tokens` into running totals inside the retry loop (every iteration, success or not);
return `ExtractionOutcome(result=..., usage=TokenUsage(total_input, total_output))` on success.
Update all 5 existing tests' fake response objects to carry a `usage=SimpleNamespace(
input_tokens=N, output_tokens=N)` attribute, and update assertions from `result.claims` to
`outcome.result.claims`.

- [x] Write a failing test (retry-then-succeed case: assert the returned `usage` sums tokens from
      **both** the failed and the succeeding attempt, not just the last one), implement, verify
      all `test_llm_extraction.py` tests pass
- [x] Commit: `feat: return real token usage from extract_claims`

### Task 2: Wire real usage into `analyze_pending_documents`

**Files:** modify `investor_intel/pipeline/analyze.py`; extend `tests/test_pipeline_analyze.py`.

Replace the character-count estimate block with `outcome = extract_claims(...)`,
`extraction = outcome.result`, `cost_tracker.record_usage(client.model,
outcome.usage.input_tokens, outcome.usage.output_tokens)`. Remove the now-unused
`_CHARS_PER_TOKEN_ESTIMATE` constant and `import json` (confirm `json` isn't used elsewhere in
the file before removing — it currently isn't). Update the 3 existing tests' fake response
`_tool_use_response()` to carry `usage=SimpleNamespace(input_tokens=N, output_tokens=N)`, and add
an assertion that `cost_tracker`'s recorded usage matches the fake's `usage` values exactly (not
just ">  0" as today) — this is the test that actually proves the estimate was replaced, not just
that something non-zero got recorded.

- [ ] Write a failing test (fake response carries a specific known `usage`; assert
      `cost_tracker.daily_total_usd()` reflects exactly that token count via
      `compute_cost_usd(model, known_input, known_output)`, not an estimate-derived value),
      implement, verify pass
- [ ] Commit: `feat: use real Anthropic token usage for cost tracking instead of a character estimate`

## Self-review notes

- **Reuse over reimplementation:** `CostTracker.record_usage` and `storage/cost_ledger.py` needed
  zero changes — they already accept raw token counts; this phase only fixes what produces those
  counts.
- **Accumulate-across-retries is the one subtle correctness requirement** — verified by tracing
  `extract_claims`'s actual retry loop rather than assuming "usage" means "the last response's
  usage."
- **Known pre-existing gap, explicitly not expanded:** cost of a fully-exhausted-retries failure
  is still untracked after this phase, same as before — flagged rather than silently left as an
  undocumented surprise.

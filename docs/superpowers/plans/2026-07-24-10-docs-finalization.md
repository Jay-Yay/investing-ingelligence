# Docs Finalization Implementation Plan

**Goal:** Close out the roadmap — real README, real Runbook, an actual (not just unit-tested)
end-to-end run of the wired pipeline, and a completion-criteria check. Phase 10 is verification
and documentation, not new code.

**Scope decision (completion criteria source):** The design doc's §6 says "사용자 스펙 §21의
완료 조건을 그대로 채택" (adopt the user's original spec §21 verbatim) — but that original
21-section user prompt was given directly in an earlier conversation and was never captured as a
file in this repo; only the design doc's own summary of it survives. This phase cannot check
against §21 verbatim because it isn't available to check against. Instead, Task 4 derives a
completion checklist from what IS in the repo: the roadmap (`00-roadmap.md`), the design doc's
architecture section (§3), and each phase's own stated scope decisions — and says so explicitly,
rather than silently presenting a derived checklist as if it were the original spec.

## Task breakdown

### Task 1: Real README.md

**Files:** modify `README.md`.

Replace the one-line placeholder with: project description, the "실제 매매 주문은 절대 실행하지
않는다" (never executes real trades) constraint stated up front, quick start (`uv sync --extra
dev`, `uv run python -m investor_intel init`, `doctor`, `collect`, `analyze`, `portfolio`,
`report`, `run-daily`), required environment variables (from `cli.py`'s `ENV_EXAMPLE`, with what
each unlocks), vault/config directory layout, a link to the design doc and roadmap for anyone
wanting the full architecture, and current implementation status (which roadmap phases are
merged — all of 01-09 plus this one).

- [x] Write README.md
- [x] Commit: `docs: write real README`

### Task 2: Real Runbook.md

**Files:** modify the `Runbook.md` scaffold text embedded in `investor_intel/cli.py`'s `init`
command (the file it writes to `vault/00_System/Runbook.md`).

Operational content: daily cadence (GitHub Actions schedule vs. manual `run-daily`), what to do
when `doctor` reports a missing credential, how to interpret `collect`/`analyze` per-source error
output (partial-failure — one bad source doesn't block the rest), cost budget behavior (analysis
stops for the day when `DAILY_LLM_BUDGET_USD` is hit, resumes next run), how `reindex` recovers
the SQLite index from the vault (the vault is the source of truth, per the design doc), and where
to add new sources/companies/investors (which YAML file, which field shape — pointing at the
`init`-scaffolded examples rather than duplicating the schema here).

- [x] Write the Runbook content into `cli.py`'s scaffold string
- [x] Regenerate check: `uv run pytest tests/test_cli_init.py -v` still passes (scaffold content
      change shouldn't break existing init tests — if it does, the test asserts on placeholder
      text and needs updating alongside)
- [x] Commit: `docs: write real Runbook operational guide`

### Task 3: End-to-end dry run

**Files:** none (verification only, in a scratch directory outside the repo).

Actually run the CLI — not mocked — in an isolated scratch directory: `init` (scaffolds
everything), `doctor` (confirms it correctly reports missing credentials in this environment),
`run-daily` (exercises collect → analyze → portfolio → report for real against the
`init`-scaffolded config). The scaffolded `sources.yaml` points at real public endpoints (Naver
RSS, Telegram web preview) — this dry run does make real, low-impact, read-only GET requests to
them (exactly the tool's intended behavior); SEC/DART collectors gracefully skip since no
credentials are configured, matching already-tested behavior. Confirm: a report file is written
to `50_Reports/Daily/`, the SQLite index has rows, `reindex` rebuilds the same index from the
vault alone.

- [x] Run the dry run, capture what actually happened (including any real network failures —
      report them, don't paper over them)
- [x] Fix anything the dry run surfaces that the unit test suite didn't catch (integration gaps
      unit tests with mocks can't see)

### Task 4: Completion criteria check + final verification

**Files:** none, or a short addition to the roadmap doc noting the check was done.

- [ ] Walk the roadmap table (phases 01-09) and confirm each is genuinely merged and its own
      plan's checkboxes are complete
- [ ] `uv run pytest -v` — full suite green
- [ ] `uv run ruff check .` — clean
- [ ] `uv run mypy investor_intel` — clean
- [ ] Update roadmap status for phase 10 to "merged to main"; commit

## Self-review notes

- **Honest about the missing §21:** Task 4's checklist is explicitly derived, not the user's
  original verbatim criteria, because the latter isn't recoverable from this repo.
- **Real verification, not just more mocks:** Task 3 is the first point in this project where the
  CLI runs against real external endpoints instead of `respx`-mocked ones — the whole point of a
  dry run is to catch what 225 passing mocked tests structurally cannot.

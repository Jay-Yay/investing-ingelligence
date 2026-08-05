# Stock Scoring System Implementation Plan

**Goal:** add a per-ticker, config-driven, deterministic 0-100 investment-attractiveness scoring
layer on top of the existing `regime/` (market-level) and `llm/portfolio_monitor.py`
(freeform per-ticker judgment) modules, without touching either. LLM involvement is split into
four narrow roles (Evidence Collector, Fundamental Analyst, Bear Case Critic, Model Reviewer)
that never assign the final score — arithmetic always happens in code, mirroring the existing
`TenbaggerVerification` convention where `total_score` is recomputed from `scores`, not trusted
from the LLM.

## Files added

- `config/scoring/{universe,global_scoring,sector_memory}.yaml` — ticker/sector registry,
  common category weights/thresholds/hard-gates, memory-sector overlay. `universe.yaml` has no
  `average_cost`/`quantity` fields by design (verified by
  `tests/test_config_loaders_scoring.py::test_universe_yaml_has_no_position_sizing_fields`).
- `investor_intel/models/config.py` — `ScoringUniverseConfig`, `GlobalScoringConfig`,
  `SectorScoringConfig`, `MetricSpec`, etc. (Pydantic models for the new YAML).
- `investor_intel/scoring/` (new package):
  - `models.py` — `Feature`, `CategoryScore`, `StockScoreResult`, `TradeSignal`, `ThesisStatus`.
  - `metric_normalizers.py` — kind-based 0-100 normalization (`growth_rate_pct`,
    `percent_passthrough`, `boolean`, `inverse_months`, `qualitative_trend`) driven entirely by
    `metric_specs` in the sector YAML, not hardcoded per-metric Python (unlike
    `regime/scoring.py`'s per-indicator functions — deliberately more config-driven since new
    metrics get added by editing YAML, not code).
  - `categories.py` — per-category weighted average with the same "missing data reweights
    proportionally, never zero-fills" principle as `regime/scoring.py::_weighted_score`.
  - `confidence.py`, `hard_gates.py`, `hysteresis.py`, `valuation_scenarios.py`,
    `price_supply_demand.py`, `earnings_revision.py`, `evaluation.py`.
  - `pipeline.py` — `compute_stock_score()`, the pure orchestrator (no I/O, fully unit-testable).
  - `snapshot.py` — point-in-time JSON snapshots under `vault/60_StockScore/processed/<ticker>/`,
    mirroring `regime/history_store.py`'s append-only + revision-preserving pattern.
- `investor_intel/llm/{evidence_collector,fundamental_analyst,bear_case_critic,model_reviewer}.py`
  + matching `config/prompts/*.md` — same tool-use + retry + `ValidationError` pattern as
  `llm/portfolio_monitor.py`.
- `investor_intel/pipeline/stock_score.py` — the only module that does real I/O (Yahoo price
  history + fundamentals, regime macro reuse, SQLite `document_assets` join for
  ticker-relevant vault documents).
- `investor_intel/reports/stock_score_renderer.py` — 12-section Markdown report.
- `investor_intel/cli.py` — new `score` Typer sub-app: `compute` (daily, LLM-free),
  `run-weekly` (LLM 4-role, event/weekly cadence only), `report`.
- `model_registry/{champion.yaml,changelog.md,challengers/}` — human-gated version tracking.
- 24 new test files under `tests/` (`test_scoring_*.py`, `test_llm_{evidence_collector,
  fundamental_analyst,bear_case_critic,model_reviewer}.py`, `test_config_loaders_scoring.py`).

## Key architectural decisions (confirmed live against the real repo, not assumed)

- **macro_liquidity category reuses `regime.scoring.compute_scores()` output** (inverted
  cooling_risk) instead of re-deriving macro conditions per ticker —
  `pipeline/stock_score._macro_liquidity_score()`, verified against the real
  `vault/60_MarketRegime/history/` data in this repo (returned 79.7 on a live run against
  today's actual regime snapshots).
- **Daily vs weekly split**: `run_score_compute()` (LLM-free) recomputes price/volume/
  fundamentals-derived features daily; valuation scenarios and EPS-revision inputs are carried
  forward unchanged from the last `run_score_weekly()` snapshot (`StockScoreSnapshot.
  valuation_scenarios`/`earnings_revision_inputs`). This keeps the new LLM roles off the daily
  cron entirely, per the user's explicit choice to protect the existing $1.5/day budget.
- **Confidence must not be sunk to 0 by categories with no per-Feature source-tier data**
  (price/macro/valuation categories compute a score directly, not from tagged `Feature` objects).
  Found and fixed during a live end-to-end run against real SK Hynix data: the first version
  returned `confidence=0.0` whenever only these "special" categories had data, which is
  systematically wrong, not just a rare edge case. Fixed by treating an empty
  `contributing_features` list as "no source-tier signal available" (neutral 0.5), not "no
  confidence at all" (see `scoring/confidence.py` `compute_confidence`).
- **Confidence penalty for missing data is capped at 0.20**, not unbounded-linear per missing
  metric — the memory sector's 47-metric list means double-digit missing counts are normal even
  with decent real coverage (coverage-based scoring already penalizes this once; an unbounded
  second penalty was found, during the same live run, to zero out confidence even when the bulk
  of *important* metrics were present).

## Verification performed

- Full existing test suite (706 tests) passes unchanged after this addition.
- `ruff check` and `mypy` clean on every new/modified file.
- `investor_intel score compute 000660.KS` run against **live** Yahoo Finance price history and
  the repo's real `vault/60_MarketRegime/` regime history — produced a real, non-fabricated
  `total_score=63.1` with correctly-populated `price_supply_demand`/`macro_liquidity` categories
  and correctly-`missing` `memory_supply_demand_pricing`/`earnings_outlook`/etc. (no weekly LLM
  run had populated those yet — this is the intended daily behavior, not a bug).
  `fundamentals-timeseries` hit a live 429 rate limit in this sandbox; the fix that makes this a
  graceful degradation (warning + missing features) instead of a crash was added and verified in
  the same session.
- `investor_intel score report 000660.KS` rendered the 12-section Markdown report from that same
  real snapshot.

## Not implemented / explicitly deferred (see spec doc §4 "알려진 한계")

- Fully automated bear/base/bull EPS×multiple selection (requires cycle-stage judgment).
- Statistical significance testing in Champion/Challenger comparison (economic-significance +
  minimum-sample gating only).
- KRX_SEMICONDUCTOR benchmark (no free Yahoo symbol).

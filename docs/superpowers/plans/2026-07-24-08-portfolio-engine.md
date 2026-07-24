# Portfolio Engine Implementation Plan

**Goal:** Build the portfolio models/loader, pure derived-value calculations, and guardrails —
the roadmap's phase 08. Consumes `Quote` (phase 06) for prices; produces the inputs phase 09's
daily report will render.

**Scope decision (recommendation generation deferred):** The design doc's data-flow line reads
"`guardrails(§12.3) → decision_status/recommendation`", but the actual investment *recommendation*
(STRONG_BUY/BUY/HOLD/REDUCE/SELL) requires synthesizing the analyst's thesis and extracted claims
— that's `llm/portfolio_impact.py`'s job (phase 09, needs both this phase's metrics and the
claims extracted in phase 07). This phase does not fabricate that judgment. What it does produce,
and what phase 09 will combine with the LLM's thesis-driven view: (1) mechanical guardrail
violations, (2) `decision_status` (`pending` when price data is stale/unavailable — an explicit,
already-documented rule, §3.4 of the design doc — otherwise `complete`), and (3) a
`max_allowed_recommendation` **cap** per symbol — e.g. a position over its concentration limit
cannot be recommended above `HOLD` regardless of thesis conviction. Phase 09 combines the LLM's
recommendation with this cap (`min` by rating order) rather than this phase inventing the rating
itself.

**Scope decision (FX conversion):** Positions may hold non-KRW `cost_currency` (e.g. USD) while
`base_currency` is KRW, but no FX-rate data source exists yet (deferred alongside market data
phase 06, which only built yfinance/CoinGecko). This phase computes market value, cost basis, and
P&L in the position's **own `cost_currency`** — not converted to `base_currency`. Cross-currency
portfolio-level aggregation (total value in KRW) is therefore also deferred; a documented gap,
not a silent wrong number.

## Global constraints

Inherited from phases 01-07: no placeholders/TODOs; pure functions here take already-fetched
data (a `Quote`/price mapping) as input — this package makes no network calls itself, matching
`calculations.py`'s stated "입력 불변" (inputs immutable) design principle.

## Task breakdown

### Task 1: Portfolio models + loader

**Files:** create `investor_intel/models/portfolio.py`; modify
`investor_intel/config/loaders.py`; test `tests/test_models_portfolio.py`,
extend `tests/test_config_loaders.py`.

**Interfaces:** `PortfolioConstraints(BaseModel)`: `horizon_max_months: int,
max_single_position_weight: float, max_sector_weight: float, leverage_allowed: bool,
short_selling_allowed: bool, options_allowed: bool` (weights as fractions 0-1, matching the
`0.60` values already in `cli.py`'s `PORTFOLIO_YAML` scaffold). `Position(BaseModel)`: `symbol:
str, name: str, asset_type: str, sector: str, quantity: float, average_cost: float,
cost_currency: str, thesis: str = "", target_price: float | None = None, stop_loss_price: float |
None = None`. `Portfolio(BaseModel)`: `as_of: date, base_currency: str, constraints:
PortfolioConstraints, positions: list[Position]`. `load_portfolio_yaml(path: Path) -> Portfolio`
— unlike the other loaders (which return a bare list), this one is a single root object matching
`portfolio.yaml`'s actual top-level shape (not a `{portfolio: [...]}` wrapper list).

- [x] Write failing tests (field validation; loader round-trips the exact `cli.py` scaffold
      shape), implement, verify pass
- [x] Commit: `feat: add Portfolio models and portfolio.yaml loader`

### Task 2: Portfolio calculations

**Files:** create `investor_intel/portfolio/__init__.py` (empty),
`investor_intel/portfolio/calculations.py`; test `tests/test_portfolio_calculations.py`.

**Interfaces:** `PositionMetrics(BaseModel)`: `symbol: str, current_price: float | None,
market_value: float | None, cost_basis: float, unrealized_pnl: float | None,
unrealized_pnl_pct: float | None, portfolio_weight: float | None, upside_to_target_pct: float |
None` — all price-derived fields are `None` when no quote is available for the symbol (feeds
Task 3's stale-price → `pending` rule). `compute_position_metrics(position: Position,
current_price: float | None, total_market_value: float | None) -> PositionMetrics`.
`compute_portfolio_metrics(positions: list[Position], prices: dict[str, float]) ->
list[PositionMetrics]` — `prices` missing a symbol means "no quote", not a `KeyError`.
`compute_sector_weights(positions: list[Position], metrics: list[PositionMetrics]) ->
dict[str, float]` — fraction of total market value per `sector`, skipping positions with no
market value.

- [x] Write failing tests (P&L arithmetic; zero-cost-basis division guarded; missing price →
      all price-derived fields `None`; portfolio weight sums to 1.0 across full-priced
      positions; sector weights aggregate correctly), implement, verify pass
- [x] Commit: `feat: add portfolio derived-value calculations`

### Task 3: Portfolio guardrails

**Files:** create `investor_intel/portfolio/guardrails.py`; test
`tests/test_portfolio_guardrails.py`.

**Interfaces:** `GuardrailViolation(BaseModel)`: `symbol: str, rule: str, message: str`.
`check_guardrails(portfolio: Portfolio, metrics: list[PositionMetrics]) ->
list[GuardrailViolation]` — checks `max_single_position_weight` and `max_sector_weight` per
`constraints`; `leverage_allowed`/`short_selling_allowed`/`options_allowed` checked against each
position's `asset_type`/`quantity` (a negative `quantity` implies a short position; `asset_type`
containing `"option"` implies an options position) — violated only when the corresponding
constraint is `false` (matches the `cli.py` scaffold's all-`false` defaults).
`decision_status_for(metrics: PositionMetrics) -> DecisionStatus` (from `models/common.py`,
reused) — `PENDING` when `current_price is None`, else `COMPLETE`.
`max_allowed_recommendation(violations: list[GuardrailViolation], symbol: str) ->
RecommendationRating | None` (from `models/common.py`, reused) — `HOLD` if any violation exists
for `symbol`, else `None` (no cap; phase 09's LLM-driven recommendation applies unmodified).

- [ ] Write failing tests (over-weight position flagged; over-weight sector flagged; short
      position flagged only when `short_selling_allowed` is false; stale price → `PENDING`;
      a clean position has no cap; a violating position caps at `HOLD`), implement, verify pass
- [ ] Commit: `feat: add portfolio guardrails and decision-status/recommendation-cap logic`

### Task 4: Full verification pass

- [ ] `uv run pytest -v` — all tests green
- [ ] `uv run ruff check .` — clean
- [ ] `uv run mypy investor_intel` — clean
- [ ] Commit any fixes; update roadmap status for phase 08 to "merged to main"

## Self-review notes

- **Pure functions, no I/O:** `portfolio/calculations.py` and `portfolio/guardrails.py` take
  already-computed data in and return data out — no vault/index/network access, matching the
  design doc's "입력 불변" principle for this package.
- **Deferred, not skipped:** LLM-driven recommendation synthesis and FX conversion are named
  out-of-scope items with stated reasons, not silently dropped.

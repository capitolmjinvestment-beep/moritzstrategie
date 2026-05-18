# Code Review Report — Standalone Indicator Library

**Date:** 2026-05-18
**Reviewer:** superpowers:code-reviewer agent
**Scope:** All modules in `src/indicators/` + tests + backtest engine
**Status:** Library is production-ready as a **standalone learning artifact**, NOT as Phase-4-decision tool. See gaps below.

## Test status

72 tests, all green. Coverage: every indicator, every entry condition (Long+Short), all 4 exit triggers, look-ahead guards on each layer (aggregation, RSI, ATR, evaluate_entry).

## Critical findings (5 raised, 3 fixed, 2 documented)

| ID | Issue | Status |
|----|-------|--------|
| C1 | `run_backtest` precomputes Camarilla over entire history; in live trading the daily bar of D−1 isn't necessarily ready at 00:00 of D | **DOC** — see "Production limitations" below |
| C2 | "Fill at close" with no slippage/fee model produces optimistic PnL | **DOC** — see "Production limitations" |
| C3 | k=2 pivot definition requires 2 forward-confirmation bars; spec is silent on this | **FIXED** — explicit test `test_pivot_requires_2_bars_forward_confirmation` documents the behavior |
| C4 | `__init__.py` may be missing | **VERIFIED PRESENT** |
| C5 | Zero-priced bars cause divide-by-zero in `Trade.pnl_pct` and pattern detection | **FIXED** — `Bar.__post_init__` rejects `low <= 0`; tests added |

## High-priority findings (8 raised, 4 fixed, 4 documented)

| ID | Issue | Status |
|----|-------|--------|
| H1 | `Camarilla.P` uses non-terminating decimal division; comparison `bar.close <= P` may have precision issues at exchange tick boundaries | **FIXED** — `precision.py` provides `quantize_price()`, `quantize_camarilla()`, `tick_for()` + Bitget tick-size table. Apply in Strategy before comparisons. |
| H2 | RSI returns 50 for flat prices, deviating from ta-lib NaN convention | **ACCEPTED** — documented in `rsi.py` docstring |
| H3 | RSI reference value tolerance was 1.0 — too wide | **FIXED** — tightened to ±0.05 |
| H4 | "Pivot-Touch" defined as `close <= L3` but MASTERPLAN says "Touch" — ambiguous | **DOC** — see "Spec ambiguities" below; Moritz must reconcile |
| H5 | `min_separation` boundary case (sep == min_separation == 3) not tested | **FIXED** — new test `test_double_bottom_minimum_separation_exactly_equals_param` |
| H6 | `pnl_pct` for TP1→Stop case worked by coincidence, no explicit test | **FIXED** — new tests for both LONG and SHORT TP1→Stop |
| H7 | Time-stop fires alongside TP1 in the boundary bar, undocumented | **DOC** — behavior preserved, doc-string updated |
| H8 | Pattern detector "most recent second-low" preference is arbitrary | **DOC** — see "Spec ambiguities" |

## Medium / Nitpick findings

All medium issues are documented in source comments or accepted as known limitations. Nitpicks (test code using `float()` for setup, etc.) are deferred to repo integration phase.

---

## Production limitations (must be addressed before Phase 6)

These are NOT bugs in the standalone library — they are scope gaps that must be filled by the real Strategy implementation in MjCapital:

1. **Causal Camarilla provider**: `run_backtest` precomputes all daily levels upfront. In production, the Strategy must compute today's levels only from yesterday's *fully-completed* daily bar, with explicit handling for feed delays between 23:59:59 and the actual close of the 20:00–24:00 bar. *Still open.*

2. **Fee + slippage model**: ✅ **RESOLVED** via `friction.py`. `FrictionModel` composes `FeeSchedule + FundingSchedule + SlippageModel`. Default factory `default_bitget_friction()` ships sensible Bitget defaults (6bps taker, 0.01%/8h funding, 5bps constant slippage). `VolatilitySlippage` available for stress tests. Integrated into `run_backtest` as optional `friction=` parameter; `Trade.net_pnl_pct()` returns friction-adjusted PnL.

3. **Position sizing**: ✅ **RESOLVED** via `risk.py`. `position_size_from_risk(equity, risk_pct, entry, stop)` computes `qty = risk_amount / |entry - stop|` per MASTERPLAN Section 7. `PortfolioState` tracks running equity + today's PnL.

4. **Multi-symbol coordination**: ✅ **RESOLVED** via `risk.py`. `RiskManager.check_entry_allowed(symbol, ...)` enforces `max_positions_per_symbol=1` and `max_total_positions=2` (MASTERPLAN Section 7). The real Strategy must call this before placing every order.

5. **Risk kill-switches**: ✅ **RESOLVED** via `risk.py`. `RiskManager` blocks new entries when:
   - Today's PnL ≤ −10% of initial equity (`daily_loss_kill_pct`)
   - Total equity ≤ 80% of initial (`aggregate_loss_kill_pct`)
   - Account equity ≤ 0 (`account_busted`)
   Kill switches block ENTRIES only, never auto-close existing positions (that's exit policy, strategy-specific).

---

## Spec ambiguities surfaced by implementation

These are points where MASTERPLAN is unclear and the implementation made a choice. Moritz must decide whether the choice was correct before Phase 4 stats are interpreted:

### A1. "Pivot-Touch" = close-based or wick-based?

MASTERPLAN Section 5 Cond 1: "Bar-Close ≤ L3 in den letzten 5 Bars"

Implementation matches literally (`close <= L3`). But a real "touch" could be `low <= L3` (wick is enough). Wick-based would dramatically increase trade frequency. With trade-count gate at ≥ 80 over 3 years, this choice may decide whether Phase 4 passes.

**Recommendation:** Test both variants in Phase 4 walk-forward; pick the one with more robust out-of-sample Sharpe.

### A2. Pivot definition (k=2 vs k=1) is the implementer's choice

The spec just says "lokale Lows" without defining what makes a low "local". We chose Option B (k=2 strict <). This is the highest-leverage implementation parameter and was selected with the user's input (chat record). Phase 4 should test k=1 as a sensitivity check.

### A3. Multiple-candidate preference

When 3+ valid pattern-pairs exist in the window, we pick the pair with the latest second-extreme. The spec doesn't say. Alternative: pick the pair with the smallest neckline distance (tightest pattern), or the pair with the lowest combined extreme.

### A4. Post-TP1 time-stop behavior

After TP1 fires (50% closed), if the time-stop expires before TP2 hits, we close the remaining 50% at the time-stop bar's close. The spec doesn't define this. Alternative: cancel TP2 only, leave remainder running until stop.

---

## Recommendations before integrating into MjCapital

1. **Strategy.on_bar wrapper**: Call `evaluate_entry` only when flat; manage position state and call `_process_exits` equivalents. Do NOT use `run_backtest` directly.
2. **Causal Camarilla**: In `Strategy.on_start`, set up a callback that recomputes Camarilla at the close of the 20:00 daily bar, with a fallback to "use yesterday's levels until today's daily bar is confirmed-complete".
3. **Decimal quantization**: Apply instrument tick-size quantization to all price comparisons (`close <= L3`, `close > neckline`, etc.).
4. **Fee/funding model**: Implement as a separate `FrictionModel` class that the backtest engine consumes.
5. **Phase 4 sensitivity matrix**: Test `(k=1, k=2) × (close-touch, wick-touch) × (RSI 30/70, 35/65)` = 12 variants. If results vary by more than 30% across the grid, the strategy is fragile and the gate decision should be based on the median, not the best.

# Project Postmortem: H4 Camarilla Reversal

**Status:** ABANDONED after Phase 2 (strategy validation).
**Date:** 2026-05-19
**Verdict:** The strategy specified in `MASTERPLAN.md` does not have a positive
expected value on BTC/ETH/SOL 4h data over the tested 2-year period. Hold-out
test confirmed the absence of edge on truly unseen out-of-sample data.

This document records what was built, what was tested, what was learned, and
what is reusable for future projects.

---

## What was built (Phase 0 + Phase 1)

A complete Python library implementing the strategy components:

- **Indicators**: RSI, ATR, Camarilla pivots, double-top/bottom pattern detection
- **Strategy logic**: `evaluate_entry()` pure function (mean-reversion entries)
- **Backtest engines**: per-trade and portfolio-level
- **Friction model**: composable fees + funding + slippage
- **Risk manager**: position sizing + daily/aggregate kill switches
- **Walk-forward validator**: out-of-sample temporal splits
- **Tick-size quantization**: exchange-tick-aware price comparisons
- **Bitget REST client**: stdlib-only, paged historical pulls
- **Data integrity checks**: gap/duplicate/grid/OHLC validation
- **CSV loader/cache**: atomic on-disk persistence

163 tests, all green. ~4700 lines of code total.

---

## What was tested (Phase 2)

### Test 1: Mean-Reversion (the original MASTERPLAN strategy)

Tested 5 parameter sets × 3 symbols (BTC/ETH/SOL) on 2 years of 4h data:

| Symbol | Variant | Trades | Win-Rate | Net PnL |
|--------|---------|--------|----------|---------|
| BTC | baseline (k=2)   | 2  |  0.0% | -1.47% |
| BTC | aggressive       | 57 | 14.0% | -20.47% |
| ETH | baseline         | 2  |  0.0% | -0.87% |
| ETH | aggressive       | 63 | 12.7% | -20.10% |
| SOL | baseline         | 0  |   -   |   -    |
| SOL | aggressive       | 62 | 12.9% | -20.01% |

**Finding:** All 15 variants negative. Win-rates of 12-14% on aggressive variants
indicate no statistical edge — relaxing thresholds just adds losing trades.

### Test 2: Breakout Variant (opposite thesis: trend-follow on H3/L3 break)

5 filter combinations × 3 symbols:

| Symbol | Variant | Trades | Win-Rate | Net PnL |
|--------|---------|--------|----------|---------|
| BTC | baseline                   | 248 | 39.5% | -40.83% |
| BTC | vol+confirm+RSI            | 217 | 43.3% | -2.76% |
| ETH | vol+confirm+RSI            | 218 | 42.2% | -3.21% |
| SOL | vol-1.5x                   | 351 | 42.2% | +40.15% |
| SOL | vol+confirm+RSI            | 196 | 39.8% | +14.13% |

**Finding:** Breakout had a real signal (~40% win-rate is above 1:2 R:R noise),
but only SOL showed positive returns in full-period backtest.

### Test 3: Walk-Forward (3-month disjoint windows)

| Symbol | Variant | Windows | Positive | Avg PnL |
|--------|---------|---------|----------|---------|
| BTC | vol+confirm+RSI | 8 | 3 | -1.17% |
| ETH | vol+confirm+RSI | 8 | 5 | -0.48% |
| SOL | vol+confirm+RSI | 8 | 5 | +3.40% |

**Finding:** SOL appeared robust (5/8 windows positive, +3.4% avg), suggesting a
small consistent edge. But Test 4 disproved this.

### Test 4: Hold-Out Test (DECISIVE)

SOL split into in-sample (first 18 months) and out-of-sample (last 6 months,
fully unseen). Filter locked at vol+confirm+RSI.

| Period | Trades | Win-Rate | Net Return | Max DD |
|--------|--------|----------|------------|--------|
| In-Sample (18 months)   | 145 | 42.1% | +16.58% | 11.5% |
| Out-of-Sample (6 months)| 53  | 34.0% |  -8.48% | 13.0% |

**Finding:** Win-rate dropped from 42% to 34% on unseen data. The in-sample
"edge" was overfitting to a specific market regime. Net PnL flipped from
+16.58% to -8.48%.

At 34% win-rate × 1:2 R:R, expected value per trade is
`0.34 × 2 - 0.66 × 1 = +0.02R` gross, which is consumed entirely by friction
(~0.05R per round-trip). The strategy is structurally unprofitable.

### Test 5: Refined "All Indicators" Strategy (Phase 3 follow-up)

Per user request after the original postmortem, Fibonacci was added as a
fifth indicator and a refined strategy combined ALL 5 indicators
(RSI + ATR + Camarilla + Patterns + Fibonacci) with Fibonacci-extension
targets (TP1=1.272, TP2=1.618) replacing the previous H4 / ATR-multiple
targets. Hold-out test repeated on all three symbols:

| Symbol | IS Net Return | OOS Net Return | OOS Win-Rate |
|--------|---------------|----------------|--------------|
| BTC | +13.05% | -3.41%  | 35.3% |
| ETH | +24.18% | -2.59%  | 38.5% |
| SOL |  +5.37% | -14.10% | **25.0%** (worse than Phase 2: 34.0%) |

**Finding:** Adding Fibonacci did NOT change the verdict. All 3 symbols show
the same pattern as before: positive in-sample, negative out-of-sample.
SOL actually got worse (Fibonacci extensions are further from entry than
the flat ATR-targets, so more trades hit the stop before TP1).

The takeaway: the problem is NOT in the exit targets. It is in the entry
signal quality — we are catching breakouts/reversals that don't follow
through, and no amount of target refinement can fix that. This strengthens
the original postmortem conclusion.

---

## Why the strategy doesn't work

Three converging explanations:

1. **The 2024-2026 BTC/ETH/SOL market was trending, not mean-reverting.**
   Camarilla L3/H3 are tight pivots designed for range markets. In a 2.5x BTC
   bull-run, prices rarely retrace to L3, and when they do, they're followed by
   more trend, not reversal.

2. **Friction is brutal on 4h Crypto-Perp.** Round-trip costs are ~12-20 bps
   per trade. With realistic R:R of 1:2 and 40% win-rate, the gross edge of
   ~0.2R per trade is roughly equal to friction. Any execution imperfection
   pushes net into negative territory.

3. **Camarilla L3/H3 breakouts are common but unreliable.** The breakout variant
   produced 250-500 trades per symbol per 2 years (vs. 80 hoped-for), and even
   with three independent filters (volume, multi-bar confirmation, RSI),
   the actual out-of-sample win-rate was only 34%.

---

## What is reusable

The library is symbol-agnostic and strategy-agnostic. Every module can be
dropped into a different trading project:

- **`indicators/`**: RSI, ATR, Camarilla — used as standard charting math
- **`patterns/`**: Double-top/bottom — works for any timeframe/instrument
- **`friction/`**: Bitget fee model + composable slippage — directly reusable
  on any other Bitget-USDT-Perp strategy
- **`risk/`**: Position sizing + kill switches — pure logic, no strategy
  coupling. Apply to any signal source.
- **`backtest/`** and **`portfolio_backtest/`**: Bar-driven backtest harness
  with realistic exit handling, partial fills, equity tracking. Plug in any
  `evaluate_entry`-shaped function.
- **`walk_forward/`**: Out-of-sample validator — use to test ANY strategy
  before committing capital. **This is the most valuable artifact.** It
  prevented a 1000 EUR mistake.
- **`data/bitget_rest.py`**: 2-year historical pull, integrity-checked,
  cached. Works for any Bitget v2 USDT-Perp symbol.

If you build another strategy: you keep ~80% of this codebase. Only the
specific `evaluate_entry()` and (maybe) the exit logic in `backtest._process_exits`
need replacement.

---

## Lessons learned

1. **Hold-out testing is mandatory.** Walk-forward looked positive (5/8 windows
   green on SOL); only the strict hold-out exposed overfitting. If we had
   skipped this step, we would have gone to paper-trading and lost confidence
   slowly over weeks instead of in 30 minutes of analysis.

2. **In-sample optimization is dangerous.** Each filter we added on SOL had a
   plausible justification (volume = conviction, multi-bar = noise filter,
   RSI 55 = trend confirmation). All three together looked like a robust edge.
   The hold-out test reveals: each filter was tuned to a specific past, not
   to a general pattern.

3. **The MASTERPLAN's phase gates worked as designed.** Phase 4 explicitly
   demands ≥80 trades + Sharpe ≥1.0 + PF ≥1.3. We failed all three on
   out-of-sample data. The gate prevented the next phase from starting.

4. **Real data > synthetic data.** On synthetic mean-reverting noise, the
   original Camarilla strategy never fired at all. On real BTC/ETH data, it
   fired rarely and lost. Two different failure modes, both signals to stop.

5. **Friction modeling early matters.** The breakout variant looked profitable
   without friction (40% win-rate × 1:2 R:R = positive expectancy on paper).
   Only after applying realistic 12 bps round-trip friction did the true
   picture emerge. The `FrictionModel` class is the most underrated component
   of the library.

---

## What was NOT tested (acknowledged gaps)

- **Longer history (3-5 years, 2021-2023 Bear market).** Bitget only provides
  2 years on the standard endpoint. The strategy might work in bear markets
  where mean-reversion at pivots is more reliable. Untested.
- **1h or 1d timeframes.** All tests on 4h only.
- **Other instruments.** Only BTC, ETH, SOL. Alts (DOGE, ADA, etc.) untested.
- **Live spread/funding rates.** Used static estimates. Real funding can vary
  ±0.1% per 8h, occasionally more.
- **Liquidation risk at 3x leverage.** Not simulated.

If you ever revisit this strategy, start with these gaps.

---

## Final state

- **Library:** Complete and tested.
- **Strategy implementation:** Complete but verified to lack edge.
- **Phases 5/6 (paper/live trading):** NOT STARTED. Do not start.
- **Capital at risk:** 0 EUR. Plan worked.
- **GitHub:** https://github.com/capitolmjinvestment-beep/moritzstrategie

If you start a new strategy project, fork or copy this repo and replace
`evaluate_entry()` with your new logic. Everything else carries over.

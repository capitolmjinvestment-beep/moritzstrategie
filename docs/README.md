# H4 Camarilla Reversal — Indicator Library

Standalone Python library for the H4 Camarilla Reversal trading strategy
described in `files/MASTERPLAN.md`.

**Status:** Production-ready as a standalone library. 145 tests, all green.
Not yet integrated into MjCapital-Scalping repo (see `MIGRATION.md`).

## Quick start

```bash
cd "/Users/moritzlitterscheidt/profi 4h "
python3 -m pytest tests/                    # run all tests
python3 run_backtest.py                     # synthetic backtest
python3 diagnose.py                         # entry-condition funnel
python3 compare_friction.py                 # fees + funding + slippage demo
python3 sensitivity_pivot_k.py              # k=1/2/3 sensitivity
```

To use the library from your own code:
```python
import sys; sys.path.insert(0, "src")  # or set PYTHONPATH=src
from indicators import (
    evaluate_entry, RiskManager, PortfolioState,
    default_bitget_friction, walk_forward,
)
```

## What's inside

```
src/indicators/
├── types.py              OHLCV Bar, Pattern, PatternResult
├── aggregation.py        4h → daily (look-ahead-safe)
├── camarilla.py          Pivot levels (H3/H4/L3/L4/P)
├── rsi.py                Wilder RSI
├── atr.py                Wilder ATR
├── patterns.py           Double-top/bottom (configurable pivot_k)
├── strategy.py           evaluate_entry() — pure entry-signal function
├── backtest.py           Per-trade sanity backtest
├── friction.py           Fees + funding + slippage (composable)
├── risk.py               Position sizing + kill switches
├── portfolio_backtest.py Strategy + Friction + Risk → equity curve
├── walk_forward.py       Out-of-sample validation across regimes
└── precision.py          Tick-size quantization for exchange compatibility

tests/                    145 tests covering every module
files/                    MASTERPLAN.md, CLAUDE.md, PHASE_1_KICKOFF.md
REVIEW.md                 Code-review findings + production limits
MIGRATION.md              Playbook for moving into MjCapital repo
```

## Three layers of backtest

The library ships three composable backtest paths. Use the right one for the question:

| Layer | Function | Question it answers |
|-------|----------|---------------------|
| Signal | `evaluate_entry(bars, idx, camarilla)` | "Does the bar at idx fire a signal?" |
| Trades | `run_backtest(bars)` | "What trades would the signal produce?" |
| Portfolio | `run_portfolio_backtest(bars)` | "What would my account look like?" |
| Validation | `walk_forward(bars)` | "Is the edge regime-robust?" |

All three share the SAME `evaluate_entry` core. Fix a bug there, all three benefit.

## End-to-end example

```python
from decimal import Decimal
from indicators import (
    EntryParams,
    PortfolioState, RiskParams,
    default_bitget_friction,
    run_portfolio_backtest, walk_forward,
)

# Load your 4h BTC bars somehow (CSV, parquet, Bitget API, ...)
bars = load_btc_4h_bars()

# Run a single portfolio backtest with realistic friction
result = run_portfolio_backtest(
    bars,
    symbol="BTCUSDT",
    initial_equity=Decimal("1000"),
    entry_params=EntryParams(pivot_k=2),
    risk_params=RiskParams(risk_per_trade_pct=Decimal("0.015")),
    friction=default_bitget_friction(),
)
print(f"Final equity: {result.final_equity}")
print(f"Trades: {result.n_trades}, Win-rate: {result.win_rate}")
print(f"Skipped by risk: {result.skipped_signals} ({result.skip_reasons})")

# Validate across regimes
report = walk_forward(bars, test_months=3, friction=default_bitget_friction())
print(f"Windows: {report.n_windows}, positive: {report.positive_windows}")
print(f"Consistency: {report.consistency}")
```

## Strategy summary (full spec in `files/MASTERPLAN.md`)

**Long setup — all four conditions must fire simultaneously:**
1. Close ≤ Camarilla L3 in last 5 bars
2. RSI(14) < 30 within last 3 bars
3. Double-bottom pattern in last 15 bars (both lows ≤ L3, ≤1.5% apart, ≥3 bars separation)
4. Current bar closes > neckline AND RSI > 30

**Exits:**
- Stop: min(both DB lows) − 0.5 × ATR(14)
- TP1 (50%): central pivot P
- TP2 (50%): H3 (long) / L3 (short)
- Time-stop: 12 bars (48h)

**Risk:**
- 1.5% equity at risk per trade
- Max 1 position per symbol, 2 across all symbols
- Kill switches: −10% daily PnL, −20% aggregate equity

**Friction (Bitget USDT-Perp defaults):**
- Taker fee 6 bps per side
- Funding 0.01% per 8h period
- Slippage 5 bps constant (or volatility-scaled via `VolatilitySlippage`)

## What's NOT here

- Real Bitget REST/WebSocket adapter (Phase 1 in MASTERPLAN)
- Order placement, position tracking, live execution (Phase 5)
- Multi-symbol bar coordination (orchestrator needed)
- Persistent trade history (database integration)
- Plotting (deliberately: no matplotlib dependency)

These all live in the MjCapital-Scalping repo. See `MIGRATION.md` for the
8-step integration playbook.

## Key design decisions

See `REVIEW.md` "Spec ambiguities" section for the four open spec questions
(touch=close vs. wick? pivot k=1/2/3? pattern preference? post-TP1 time-stop?).
Three have implementation defaults; one (touch definition) needs your call
before Phase 4.

## Testing philosophy

Every module is tested for:
- Correctness against known reference values (RSI vs. Wilder dataset, ATR, Camarilla math)
- Look-ahead protection (each indicator explicitly tested for no future-data leakage)
- Edge cases (empty input, insufficient history, zero-price bars, boundary windows)
- Decimal-only outputs (no float leaks anywhere downstream)

Run the full suite with `pytest tests/` — should complete in < 1 second.

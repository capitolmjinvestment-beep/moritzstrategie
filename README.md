# moritzstrategie

H4 Camarilla Reversal trading strategy for Bitget USDT-Perpetual futures (BTC/ETH/SOL).

**Status:** Core indicator library complete (145 tests, all green). Live execution and Bitget API integration not yet implemented.

## Strategy in one paragraph

Mean-reversion on the 4-hour timeframe. When price closes at Camarilla L3 (long) or H3 (short), RSI is in oversold/overbought territory, and a double-bottom/top pattern has formed at the level, enter on the neckline breakout. Stop at the pattern's extreme minus 0.5 × ATR. Take profit 50% at central pivot P, the rest at H3/L3. Time-stop after 12 bars (48h).

See `docs/MASTERPLAN.md` for the full specification.

## Quick start

```bash
git clone https://github.com/capitolmjinvestment-beep/moritzstrategie.git
cd moritzstrategie
python3 -m pip install -e ".[dev]"
python3 -m pytest tests/                    # 145/145 should pass
python3 scripts/run_backtest.py             # synthetic backtest
python3 scripts/diagnose.py                 # entry-condition funnel
python3 scripts/compare_friction.py         # fee + funding + slippage demo
python3 scripts/sensitivity_pivot_k.py      # pivot-k sensitivity
```

## Repository layout

```
src/moritzstrategie/      Python package (all modules)
  types.py                OHLCV Bar, Pattern, PatternResult
  aggregation.py          4h → daily (look-ahead-safe)
  camarilla.py            Pivot levels (H3/H4/L3/L4/P/...)
  rsi.py, atr.py          Wilder indicators
  patterns.py             Double-top/bottom detection
  strategy.py             evaluate_entry() — pure entry function
  backtest.py             Per-trade sanity backtest
  friction.py             Fees + funding + slippage (composable)
  risk.py                 Position sizing + kill switches
  portfolio_backtest.py   Strategy + Friction + Risk → equity curve
  walk_forward.py         Out-of-sample validation
  precision.py            Tick-size quantization

tests/                    145 tests covering every module
scripts/                  CLI utilities (backtest, diagnose, sensitivity)
docs/
  MASTERPLAN.md           Strategy specification (single source of truth)
  CLAUDE.md               Working instructions for code-gen agents
  PHASE_1_KICKOFF.md      First implementation task
  REVIEW.md               Code-review findings + production limits
  MIGRATION.md            (Historical) standalone → repo playbook
```

## What's done vs. what's next

**Done (Phase 0 = "Library"):**
- All indicators (RSI, ATR, Camarilla, Double-Top/Bottom)
- Entry-signal logic (`evaluate_entry`)
- Backtest engine (per-trade + portfolio-level)
- Friction model (fees + funding + slippage)
- Risk manager (sizing + kill switches)
- Walk-forward validator
- Tick-size quantization for exchange compatibility

**Next (per MASTERPLAN.md):**
- Phase 1: Bitget data pipeline (REST historical + WebSocket live, 4h bars)
- Phase 2: Strategy adapter (wire `evaluate_entry` into a `Strategy.on_bar()` runner)
- Phase 3: Real-data sanity checks
- Phase 4: Walk-forward backtest with hard gates (Sharpe ≥ 1.0, ≥80 trades)
- Phase 5: Paper trading on Bitget testnet
- Phase 6: Live with 1000€ / 3x leverage on BTC/ETH/SOL

## Risk discipline (from MASTERPLAN.md)

- 1.5% equity at risk per trade (NEVER higher)
- Max 1 position per symbol, max 2 total
- Daily loss kill: −10% of starting equity
- Aggregate loss kill: −20% of starting equity
- Leverage 3x maximum (not 10x — risk is controlled via position sizing, not leverage)
- Phase gates must pass before next phase; no skipping

## License

Proprietary. Do not distribute.

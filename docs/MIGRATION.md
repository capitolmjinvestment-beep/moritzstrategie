# Migration Guide: Standalone Library → MjCapital Repo

This document is the playbook for moving the standalone indicator library
(currently at `/Users/moritzlitterscheidt/profi 4h /`) into the real
MjCapital-Scalping repo once you have it.

**Estimated effort:** 1–2 hours of mechanical work + however long Phase 1–2
take in the MASTERPLAN.

## Pre-flight check (before you touch anything)

1. ✅ Confirm 126 tests still green: `pytest tests/`
2. ✅ Read `REVIEW.md` (esp. "Production limitations" and "Spec ambiguities")
3. ✅ Make a backup of the standalone folder before any deletions
4. ✅ Have the MjCapital repo cloned and pytest working locally

## Step 1: Copy indicators package

```bash
# In MjCapital repo:
mkdir -p src/scalping/indicators
cp /path/to/standalone/src/indicators/*.py src/scalping/indicators/
```

Update imports inside each file:
```python
# OLD (standalone)
from .types import Bar
from .friction import FrictionModel

# NEW (repo) — only if repo uses absolute imports
from scalping.indicators.types import Bar
from scalping.indicators.friction import FrictionModel
```

If MjCapital already uses relative imports inside packages, no change needed.

## Step 2: Copy tests

```bash
mkdir -p tests/scalping/indicators
cp /path/to/standalone/tests/test_*.py tests/scalping/indicators/
```

Adjust `conftest.py`:
```python
# Drop the standalone sys.path hack; repo should have proper packaging
# Old:
#   sys.path.insert(0, str(ROOT / "src"))
# New: trust pyproject.toml or setup.py to put src on path
```

Run: `pytest tests/scalping/indicators/` — all 126 should pass.

## Step 3: Wire `evaluate_entry` into Strategy.on_bar

In MjCapital, locate the existing 1m-scalper Strategy class (likely
`src/scalping/strategy/base.py` or similar). The H4 strategy follows the
same interface but with a 4h-bar feeder.

```python
# src/scalping/strategy/camarilla_h4.py (NEW FILE)
from decimal import Decimal
from scalping.indicators.aggregation import aggregate_to_daily
from scalping.indicators.camarilla import compute_camarilla
from scalping.indicators.friction import default_bitget_friction
from scalping.indicators.risk import PortfolioState, RiskManager, RiskParams
from scalping.indicators.strategy import EntryParams, Side, evaluate_entry

class CamarillaH4Strategy(YourBaseStrategy):
    def __init__(self, symbols, initial_equity):
        self.symbols = symbols  # ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        self.state = PortfolioState.fresh(Decimal(initial_equity))
        self.risk = RiskManager(self.state, RiskParams())
        self.friction = default_bitget_friction()  # for sizing decisions, not live exec
        self.bars_4h = {sym: [] for sym in symbols}
        self.daily_levels = {sym: None for sym in symbols}

    def on_4h_bar_close(self, symbol, bar):
        self.bars_4h[symbol].append(bar)
        # Recompute daily levels at midnight UTC
        if bar.ts.hour == 0:
            self._refresh_daily_levels(symbol)
        # Evaluate entry only if flat for this symbol
        if self.state.open_positions.get(symbol, 0) == 0:
            sig = evaluate_entry(
                self.bars_4h[symbol],
                len(self.bars_4h[symbol]) - 1,
                self.daily_levels[symbol],
                params=EntryParams(),
            )
            if sig is not None:
                decision = self.risk.check_entry_allowed(symbol, sig.entry_price, sig.stop_price)
                if decision.allowed:
                    self.place_order(symbol, sig.side, decision.position_qty,
                                     sig.entry_price, sig.stop_price,
                                     sig.tp1_price, sig.tp2_price)
                    self.state.open_position(symbol)
                else:
                    self.log.info(f"entry skipped: {decision.reason}")
```

## Step 4: Wire daily-level computation (the C1 fix from REVIEW.md)

The standalone `run_backtest` precomputes Camarilla levels for the whole dataset
upfront. **This is wrong for live trading** because at 00:00 of day D you can't
yet have day D-1's "completed" daily bar with 100% certainty (feed delay).

```python
def _refresh_daily_levels(self, symbol):
    """Compute today's Camarilla levels from YESTERDAY'S confirmed daily bar."""
    daily = aggregate_to_daily(self.bars_4h[symbol])
    if len(daily) < 1:
        return  # not enough data
    # Use the most recent COMPLETE daily bar (last entry from aggregate_to_daily,
    # which already drops the current incomplete day)
    yesterday = daily[-1]
    self.daily_levels[symbol] = compute_camarilla(yesterday)
```

Critical: `aggregate_to_daily` only returns complete days (validated by the
hour-grid check), so `daily[-1]` is always yesterday or earlier — never today.
This automatically handles feed delays.

## Step 5: Handle the Camarilla tick-size precision (the H1 fix from REVIEW.md)

When comparing `bar.close <= L3` on real prices, the non-terminating decimal
expansion of `(H+L+C)/3` can cause sporadic equality mismatches.

Add quantization in your Strategy:
```python
from decimal import Decimal, ROUND_HALF_UP

# Bitget BTCUSDT-PERP tick size is 0.1, ETH = 0.01, SOL = 0.001 etc.
TICK_SIZES = {
    "BTCUSDT": Decimal("0.1"),
    "ETHUSDT": Decimal("0.01"),
    "SOLUSDT": Decimal("0.001"),
}

def _quantize(price: Decimal, tick: Decimal) -> Decimal:
    return (price / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick

# Apply before any comparison:
l3_quantized = _quantize(camarilla["L3"], TICK_SIZES[symbol])
```

## Step 6: Replace the standalone backtest with the repo's

`run_backtest` and `run_portfolio_backtest` are SANITY tools. The real Phase 4
backtest must use MjCapital's existing backtest infrastructure (which presumably
handles multi-symbol, walk-forward, proper equity-curve plotting, etc.).

You can KEEP the standalone backtest as a smoke-test script:
```bash
# In MjCapital repo, keep a quick-sanity script:
scripts/sanity_h4_camarilla.py  # uses standalone run_portfolio_backtest
```

Useful to detect regressions quickly without running the full backtest pipeline.

## Step 7: Phase 4 walk-forward setup

For the MASTERPLAN Phase 4 gate (Sharpe ≥ 1.0, PF ≥ 1.3, ≥80 trades), don't
just run one long backtest. Use walk-forward:

```python
def walk_forward(bars, train_months=12, test_months=3):
    results = []
    start_idx = 0
    # 1y train + 3m test, slide forward 3m at a time
    bars_per_month = 6 * 30  # 6 4h-bars per day, 30 days
    while start_idx + (train_months + test_months) * bars_per_month <= len(bars):
        train_end = start_idx + train_months * bars_per_month
        test_end = train_end + test_months * bars_per_month
        test_bars = bars[train_end:test_end]
        # NOTE: we don't actually train anything — this is rule-based.
        # The walk-forward serves as out-of-sample validation across time periods.
        r = run_portfolio_backtest(test_bars, friction=default_bitget_friction())
        results.append((test_bars[0].ts, r))
        start_idx += test_months * bars_per_month
    return results
```

If Sharpe is consistently > 1.0 across 5+ test periods, you have a real edge.
If it's only 1.0 in one period and 0.2 in others, you're seeing overfitting
to a specific market regime.

## Step 8: Sensitivity analysis on real data

Run the included `sensitivity_pivot_k.py` script on real Bitget 4h CSV data:
```bash
python scripts/sensitivity_pivot_k.py data/BTCUSDT_4h_2023-2025.csv
```

Decide based on result (see "Spec ambiguities" in REVIEW.md):
- k=2 gives 80 trades/year with 60% win rate → keep it
- k=1 gives 150 trades but win-rate drops to 35% → noise, reject
- k=3 gives same as k=2 → over-engineering, keep k=2

## Final checklist before Phase 5 (paper trading)

- [ ] All 126 standalone tests pass in the repo
- [ ] MjCapital existing tests still pass (no regression)
- [ ] `run_portfolio_backtest` produces > 0 trades on real BTC 4h 2023 data
- [ ] Walk-forward Sharpe ≥ 1.0 across 4+ periods
- [ ] Tick-size quantization applied to all price comparisons
- [ ] Daily-level refresh happens at 00:00 UTC, not on first bar of new day
- [ ] Risk-Manager kill switches verified with simulated -10% day
- [ ] Position sizing produces realistic Bitget quantities (no 0.0000001 BTC orders)

## What this guide does NOT cover

You'll need to figure out from MjCapital itself:
- Exact Strategy base-class interface (`on_bar` vs `on_event` vs `tick` callback)
- Bitget WebSocket subscription for 4h bars (separate from REST historical)
- Order placement API (Bitget USDT-Perp specifics: leverage setting, position mode,
  isolation/cross margin)
- Logging and metrics integration
- Database/persistence for trade history
- Deployment + monitoring infrastructure

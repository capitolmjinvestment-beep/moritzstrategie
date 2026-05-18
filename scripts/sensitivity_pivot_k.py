#!/usr/bin/env python3
"""Sensitivity analysis: how does pivot_k change strategy behavior?

Runs the same backtest with k=1 (loose), k=2 (default), k=3 (strict) and
prints the diff in trade count, win rate, gross PnL, and friction-adjusted net.

Use to answer MASTERPLAN ambiguity A2: "what's the right k?"

Rule of thumb interpreting results:
  - If k=1 has 3x trades but same/worse PnL -> noise, stay at k=2
  - If k=1 has slightly more trades AND better PnL -> consider k=1
  - If k=3 has same trades as k=2 but cleaner -> stay at k=2 (k=3 over-engineering)
  - Big variance across k -> strategy is fragile, look elsewhere for edge
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from moritzstrategie.backtest import run_backtest  # noqa: E402
from moritzstrategie.friction import default_bitget_friction  # noqa: E402
from moritzstrategie.strategy import EntryParams  # noqa: E402
from scripts.run_backtest import load_csv, synthetic_bars  # noqa: E402


def _summary(trades: list) -> dict:
    closed = [t for t in trades if t.closed]
    if not closed:
        return {"n": 0}
    pnls = [t.pnl_pct() for t in closed]
    nets = [t.net_pnl_pct() for t in closed]
    winners = sum(1 for p in pnls if p > 0)
    return {
        "n": len(closed),
        "winners": winners,
        "win_rate": Decimal(winners) / Decimal(len(closed)),
        "gross_total_pct": sum(pnls, start=Decimal("0")),
        "net_total_pct": sum(nets, start=Decimal("0")),
        "avg_gross": sum(pnls, start=Decimal("0")) / Decimal(len(closed)),
        "avg_net": sum(nets, start=Decimal("0")) / Decimal(len(closed)),
    }


def main() -> int:
    if len(sys.argv) > 1:
        bars = load_csv(Path(sys.argv[1]))
        src = sys.argv[1]
    else:
        bars = synthetic_bars(n_days=365)
        src = "synthetic 1y"

    friction = default_bitget_friction()
    print(f"\nSensitivity (data: {src}, {len(bars)} bars, friction=bitget-default)\n")
    print(f"  {'k':>3} {'trades':>7} {'wins':>5} {'win%':>7} "
          f"{'gross%':>9} {'net%':>9} {'avg-net%':>10}")
    print(f"  {'-'*3} {'-'*7} {'-'*5} {'-'*7} {'-'*9} {'-'*9} {'-'*10}")

    for k in (1, 2, 3):
        params = EntryParams(pivot_k=k)
        trades = run_backtest(bars, entry_params=params, friction=friction)
        s = _summary(trades)
        if s["n"] == 0:
            print(f"  {k:>3} {'-':>7} {'-':>5} {'-':>7} {'-':>9} {'-':>9} {'-':>10}  (no trades)")
            continue
        print(f"  {k:>3} {s['n']:>7} {s['winners']:>5} "
              f"{float(s['win_rate'])*100:>6.1f}% "
              f"{float(s['gross_total_pct'])*100:>+8.2f}% "
              f"{float(s['net_total_pct'])*100:>+8.2f}% "
              f"{float(s['avg_net'])*100:>+9.3f}%")

    print("\nNote: on synthetic data, expect 0 trades across all k -- the strategy is")
    print("genuinely strict. Run with real Bitget 4h data for meaningful sensitivity.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

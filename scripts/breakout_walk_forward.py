#!/usr/bin/env python3
"""Walk-forward validation of the breakout strategy variants.

Runs the top-2 filter combinations from strategy_explore.py on disjoint
3-month windows over the full 2-year history for BTC/ETH/SOL.

Output: number of positive vs negative windows per (symbol, variant),
plus avg per-window PnL. Indicates whether the in-sample edge survives
out-of-sample temporal splits.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from moritzstrategie.data.loader import load  # noqa: E402

# Reuse the breakout runner from the explore script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_explore import run_breakout_backtest  # noqa: E402


SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
VARIANTS = [
    ("BR vol-1.5x",        {"volume_mult": Decimal("1.5"), "confirm_bars": 1,
                            "rsi_strict_threshold": Decimal("50")}),
    ("BR vol+confirm+RSI", {"volume_mult": Decimal("1.5"), "confirm_bars": 2,
                             "rsi_strict_threshold": Decimal("55")}),
]


def main():
    window_bars = 6 * 90  # 90 days × 6 bars/day
    warmup = 60

    print("=" * 78)
    print("BREAKOUT WALK-FORWARD (3-month disjoint windows, 2-year data)")
    print("=" * 78)
    print(f"{'symbol':<10}{'variant':<24}"
          f"{'windows':>8}{'pos':>5}{'neg':>5}{'avg-pnl%':>11}{'pos-rate':>10}")
    print("-" * 78)

    for sym in SYMBOLS:
        bars = load(sym, "4H")
        for label, kwargs in VARIANTS:
            cursor = warmup
            n_pos = n_neg = 0
            total_pnl = Decimal("0")
            n_windows = 0
            while cursor + window_bars <= len(bars):
                sub = bars[max(0, cursor - warmup):cursor + window_bars]
                r = run_breakout_backtest(sub, symbol=sym, **kwargs)
                n_windows += 1
                if r["trades"] > 0:
                    if r["total_pnl_pct"] > 0:
                        n_pos += 1
                    else:
                        n_neg += 1
                    total_pnl += r["total_pnl_pct"]
                cursor += window_bars
            avg = float(total_pnl / Decimal(n_windows)) * 100 if n_windows else 0.0
            pos_rate = n_pos / n_windows if n_windows else 0
            print(f"{sym:<10}{label:<24}{n_windows:>8}{n_pos:>5}{n_neg:>5}"
                  f"{avg:>+10.2f}%{pos_rate:>9.0%}", flush=True)
        print()


if __name__ == "__main__":
    main()

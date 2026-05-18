#!/usr/bin/env python3
"""Diagnose why the strategy fires (or doesn't) on given bars.

Outputs a funnel that shows how often each entry condition is met.
Use to validate that the strategy isn't dead-locked at one step.
"""

from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from moritzstrategie.aggregation import aggregate_to_daily  # noqa: E402
from moritzstrategie.camarilla import compute_camarilla  # noqa: E402
from moritzstrategie.patterns import detect_double_bottom, detect_double_top  # noqa: E402
from moritzstrategie.rsi import compute_rsi  # noqa: E402
from scripts.run_backtest import load_csv, synthetic_bars  # noqa: E402


def diagnose(bars: list) -> None:
    print(f"\nbars: {len(bars)}")
    closes = [b.close for b in bars]
    print(f"close range: {min(closes):.2f} .. {max(closes):.2f}")

    daily = aggregate_to_daily(bars)
    print(f"complete days: {len(daily)}")

    levels_by_date: dict[datetime, dict[str, Decimal]] = {}
    for i, d in enumerate(daily):
        if i + 1 < len(daily):
            levels_by_date[daily[i + 1].ts] = compute_camarilla(d)

    rsi = compute_rsi(closes, period=14)
    rsi_below_30 = sum(1 for v in rsi if v is not None and v < Decimal("30"))
    rsi_above_70 = sum(1 for v in rsi if v is not None and v > Decimal("70"))
    print(f"RSI < 30: {rsi_below_30}    RSI > 70: {rsi_above_70}")

    for side, threshold_key, op, rsi_op, detect_fn in [
        ("LONG",  "L3", lambda close, lvl: close <= lvl, lambda v: v < Decimal("30"), detect_double_bottom),
        ("SHORT", "H3", lambda close, lvl: close >= lvl, lambda v: v > Decimal("70"), detect_double_top),
    ]:
        c1 = c2 = c3 = c4 = 0
        for i in range(15, len(bars)):
            day_start = bars[i].ts.replace(hour=0, minute=0, second=0, microsecond=0)
            cam = levels_by_date.get(day_start)
            if cam is None:
                continue
            lvl = cam[threshold_key]
            if not any(op(bars[j].close, lvl) for j in range(max(0, i - 4), i + 1)):
                continue
            c1 += 1
            rsi_recent = [rsi[j] for j in range(max(0, i - 2), i + 1) if rsi[j] is not None]
            if not any(rsi_op(v) for v in rsi_recent if v is not None):
                continue
            c2 += 1
            pat = detect_fn(bars[max(0, i - 14): i + 1], level_threshold=lvl)
            if pat.pattern == pat.pattern.NONE:
                continue
            c3 += 1
            cur_rsi = rsi[i]
            cur_close = bars[i].close
            if cur_rsi is None or pat.neckline is None:
                continue
            if side == "LONG":
                if cur_close > pat.neckline and cur_rsi > Decimal("30"):
                    c4 += 1
            else:
                if cur_close < pat.neckline and cur_rsi < Decimal("70"):
                    c4 += 1

        print(f"\n--- {side} funnel ---")
        print(f"  Cond1 (pivot touch in last 5):  {c1}")
        print(f"  & Cond2 (RSI extreme in last 3): {c2}")
        print(f"  & Cond3 (pattern detected):     {c3}")
        print(f"  & Cond4 (trigger fires):        {c4}")


def main() -> int:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if not path.exists():
            print(f"file not found: {path}", file=sys.stderr)
            return 1
        bars = load_csv(path)
        print(f"loaded from {path}")
    else:
        bars = synthetic_bars(n_days=365)
        print("using synthetic data (1 year)")
    diagnose(bars)
    return 0


if __name__ == "__main__":
    sys.exit(main())

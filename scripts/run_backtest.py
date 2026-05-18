#!/usr/bin/env python3
"""Sanity backtest runner.

Usage:
  python3 run_backtest.py                # uses built-in synthetic data
  python3 run_backtest.py path/to/bars.csv

CSV format: ts,open,high,low,close,volume  (header row required, ts in UTC ISO format).
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from random import Random

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from moritzstrategie.backtest import run_backtest, summarize  # noqa: E402
from moritzstrategie.types import Bar  # noqa: E402


UTC = timezone.utc


def synthetic_bars(n_days: int = 365, seed: int = 42) -> list[Bar]:
    """Volatile mean-reverting walk with bursts to trigger the strategy.

    The strategy needs:
      - Closes that pierce L3/H3 (= about 27.5% range moves intraday)
      - RSI extremes (= sustained directional pushes)
      - Double-bottoms/tops at those levels

    Plain Gaussian noise won't produce these; we add regime shocks every ~30 days.
    """
    rng = Random(seed)
    bars: list[Bar] = []
    price = 100.0
    start = datetime(2024, 1, 1, tzinfo=UTC)
    n_bars = n_days * 6

    for i in range(n_bars):
        # Periodic regime: ~7-day push followed by reversion
        day = i // 6
        if day % 30 < 7:
            drift = -0.6  # crash phase
        elif 7 <= day % 30 < 14:
            drift = +0.6  # recovery phase
        else:
            drift = (100 - price) * 0.01  # slow mean-reversion
        shock = rng.gauss(0, 2.5)
        new_close = max(1.0, price + drift + shock)
        high = max(price, new_close) + abs(rng.gauss(0, 1.0))
        low = min(price, new_close) - abs(rng.gauss(0, 1.0))
        bars.append(
            Bar(
                ts=start + timedelta(hours=4 * i),
                open=Decimal(f"{price:.4f}"),
                high=Decimal(f"{high:.4f}"),
                low=Decimal(f"{low:.4f}"),
                close=Decimal(f"{new_close:.4f}"),
                volume=Decimal("1"),
            )
        )
        price = new_close
    return bars


def load_csv(path: Path) -> list[Bar]:
    bars: list[Bar] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = datetime.fromisoformat(row["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            bars.append(
                Bar(
                    ts=ts,
                    open=Decimal(row["open"]),
                    high=Decimal(row["high"]),
                    low=Decimal(row["low"]),
                    close=Decimal(row["close"]),
                    volume=Decimal(row.get("volume") or "1"),
                )
            )
    return bars


def main() -> int:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if not path.exists():
            print(f"file not found: {path}", file=sys.stderr)
            return 1
        bars = load_csv(path)
        print(f"loaded {len(bars)} bars from {path}")
    else:
        bars = synthetic_bars(n_days=365)
        print(f"using {len(bars)} synthetic bars (1 year of 4h data)")

    trades = run_backtest(bars)
    print(f"\n=== {len(trades)} trades ===")
    for i, t in enumerate(trades):
        side = "LONG " if t.side.value == "long" else "SHORT"
        exits = ",".join(e.reason for e in t.exits) or "OPEN"
        pnl = f"{t.pnl_pct() * 100:+.2f}%"
        print(f"#{i+1:3d}  {side}  entry={t.entry_price:>9}  "
              f"stop={t.stop_price:>9}  tp1={t.tp1_price:>9}  tp2={t.tp2_price:>9}  "
              f"exits=[{exits}]  pnl={pnl}")

    s = summarize(trades)
    print("\n=== summary ===")
    for k, v in s.items():
        if isinstance(v, Decimal):
            print(f"  {k:<15} {float(v):>10.4f}")
        else:
            print(f"  {k:<15} {v}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

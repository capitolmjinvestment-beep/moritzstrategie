#!/usr/bin/env python3
"""Time-stop sensitivity: maybe the strategy needs more time for TPs to play out.

Tests [12, 24, 48, 9999] bars (= 48h, 96h, 192h, effectively-disabled) on
hold-out (18mo IS / 6mo OOS) for BTC/ETH/SOL using the refined Fibonacci-target
breakout.

The hypothesis: with 12 bars (48h) we might be cutting trades short before
TP1 (1.272 Fibonacci extension) is reached. Looser time-stops should:
  - Slightly improve win-rate (more time = more TPs hit)
  - Increase friction cost (more funding paid on long holds)
  - Increase variance (one bad trade can run far against us before bar 9999)

Looking for: a value where OOS net return flips from negative to positive.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from moritzstrategie.aggregation import aggregate_to_daily
from moritzstrategie.backtest import _process_exits, Trade
from moritzstrategie.camarilla import compute_camarilla
from moritzstrategie.data.loader import load
from moritzstrategie.friction import default_bitget_friction
from moritzstrategie.risk import PortfolioState, RiskManager
from moritzstrategie.strategy import Side
from refined_full_validation import evaluate_breakout_fib


def run_fib_with_timestop(bars, symbol, time_stop_bars: int,
                          initial_equity=Decimal("1000")):
    state = PortfolioState.fresh(initial_equity)
    rm = RiskManager(state)
    friction = default_bitget_friction()
    daily = aggregate_to_daily(bars)
    levels_by_date = {}
    for i, d in enumerate(daily):
        if i + 1 < len(daily):
            levels_by_date[daily[i + 1].ts] = compute_camarilla(d)
    trades_pnl = []
    open_trade = None
    for i, bar in enumerate(bars):
        day_start = bar.ts.replace(hour=0, minute=0, second=0, microsecond=0)
        cam = levels_by_date.get(day_start)
        if open_trade is not None:
            _process_exits(open_trade, bar, i,
                           time_stop_bars=time_stop_bars, friction=friction)
            if open_trade.closed:
                pnl = open_trade.net_pnl_pct() * initial_equity * Decimal("0.5")
                state.realize_pnl(pnl, when=open_trade.exits[-1].ts)
                state.close_position(symbol)
                trades_pnl.append(pnl)
                open_trade = None
        if open_trade is None and cam is not None:
            sig = evaluate_breakout_fib(bars, i, cam)
            if sig is not None:
                if sig.side == Side.LONG and (sig.tp1_price <= sig.entry_price or
                                              sig.tp2_price <= sig.entry_price):
                    continue
                if sig.side == Side.SHORT and (sig.tp1_price >= sig.entry_price or
                                               sig.tp2_price >= sig.entry_price):
                    continue
                dec = rm.check_entry_allowed(symbol, sig.entry_price, sig.stop_price)
                if dec.allowed:
                    open_trade = Trade(
                        side=sig.side, entry_idx=i, entry_ts=bar.ts,
                        entry_price=sig.entry_price, stop_price=sig.stop_price,
                        tp1_price=sig.tp1_price, tp2_price=sig.tp2_price,
                        friction_pct=friction.fee_cost(Decimal("1"), is_taker=True),
                    )
                    state.open_position(symbol)
    return state.current_equity, trades_pnl


def main():
    print("=" * 80)
    print("TIME-STOP SENSITIVITY (refined Fib-TP strategy, 6-month OOS)")
    print("=" * 80)
    print(f"{'symbol':<10}{'time-stop':<14}{'IS-trades':>10}{'IS-WR%':>8}"
          f"{'IS-net%':>10}{'OOS-trades':>11}{'OOS-WR%':>9}{'OOS-net%':>10}")
    print("-" * 80)

    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        bars = load(sym, "4H")
        if not bars:
            continue
        cutoff = len(bars) - 6 * 30 * 6  # 6-month OOS
        is_bars = bars[:cutoff]
        oos_bars = bars[cutoff - 60:]

        for ts in [12, 24, 48, 9999]:
            label = "disabled" if ts >= 1000 else f"{ts}-bar ({ts*4}h)"
            eq_is, tr_is = run_fib_with_timestop(is_bars, sym, ts)
            eq_oos, tr_oos = run_fib_with_timestop(oos_bars, sym, ts)
            is_n = len(tr_is); oos_n = len(tr_oos)
            is_wr = sum(1 for p in tr_is if p > 0) / is_n * 100 if is_n else 0
            oos_wr = sum(1 for p in tr_oos if p > 0) / oos_n * 100 if oos_n else 0
            is_ret = float((eq_is - Decimal("1000")) / Decimal("1000")) * 100
            oos_ret = float((eq_oos - Decimal("1000")) / Decimal("1000")) * 100
            print(f"{sym:<10}{label:<14}{is_n:>10}{is_wr:>7.1f}%{is_ret:>+9.2f}%"
                  f"{oos_n:>11}{oos_wr:>8.1f}%{oos_ret:>+9.2f}%", flush=True)
        print()


if __name__ == "__main__":
    main()

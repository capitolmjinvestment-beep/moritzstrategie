#!/usr/bin/env python3
"""SOL-only validation: hold-out test + drawdown analysis.

Splits 2-year SOL history into:
  - In-Sample (IS):  first 18 months (used to pick filter)
  - Out-of-Sample (OOS):  last 6 months (truly unseen, decides go/no-go)

Reports for both:
  - Trade count, win-rate, net PnL
  - Equity curve metrics: max drawdown, longest losing streak,
    worst single trade, max consecutive losses
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from moritzstrategie.aggregation import aggregate_to_daily  # noqa: E402
from moritzstrategie.backtest import _process_exits, Trade  # noqa: E402
from moritzstrategie.camarilla import compute_camarilla  # noqa: E402
from moritzstrategie.data.loader import load  # noqa: E402
from moritzstrategie.friction import default_bitget_friction  # noqa: E402
from moritzstrategie.risk import PortfolioState, RiskManager  # noqa: E402
from moritzstrategie.types import Bar  # noqa: E402
from strategy_explore import evaluate_breakout_entry  # noqa: E402


def run_with_equity_curve(bars: Sequence[Bar], symbol: str = "SOLUSDT",
                          volume_mult=Decimal("1.5"), confirm_bars=2,
                          rsi_strict_threshold=Decimal("55"),
                          initial_equity=Decimal("1000")):
    """Run breakout backtest and track equity curve per closed trade."""
    state = PortfolioState.fresh(initial_equity)
    rm = RiskManager(state)
    friction = default_bitget_friction()

    daily = aggregate_to_daily(bars)
    levels_by_date = {}
    for i, d in enumerate(daily):
        if i + 1 < len(daily):
            levels_by_date[daily[i + 1].ts] = compute_camarilla(d)

    equity_curve = [(bars[0].ts if bars else None, initial_equity)]
    trades_pnl: list[Decimal] = []
    open_trade = None

    for i, bar in enumerate(bars):
        day_start = bar.ts.replace(hour=0, minute=0, second=0, microsecond=0)
        cam = levels_by_date.get(day_start)
        if open_trade is not None:
            _process_exits(open_trade, bar, i, time_stop_bars=12, friction=friction)
            if open_trade.closed:
                # Normalise net_pnl_pct into USDT delta via 0.5 × initial_equity scaling
                # (same approach as run_breakout_backtest for fair comparison)
                pnl_abs = open_trade.net_pnl_pct() * initial_equity * Decimal("0.5")
                state.realize_pnl(pnl_abs, when=open_trade.exits[-1].ts)
                state.close_position(symbol)
                trades_pnl.append(pnl_abs)
                equity_curve.append((open_trade.exits[-1].ts, state.current_equity))
                open_trade = None
        if open_trade is None and cam is not None:
            sig = evaluate_breakout_entry(
                bars, i, cam,
                volume_mult=volume_mult, confirm_bars=confirm_bars,
                rsi_strict_threshold=rsi_strict_threshold,
            )
            if sig is not None:
                dec = rm.check_entry_allowed(symbol, sig.entry_price, sig.stop_price)
                if dec.allowed:
                    open_trade = Trade(
                        side=sig.side, entry_idx=i, entry_ts=bar.ts,
                        entry_price=sig.entry_price, stop_price=sig.stop_price,
                        tp1_price=sig.tp1_price, tp2_price=sig.tp2_price,
                        friction_pct=friction.fee_cost(Decimal("1"), is_taker=True),
                    )
                    state.open_position(symbol)
    return state.current_equity, trades_pnl, equity_curve


def max_drawdown(equity_curve: list) -> tuple[Decimal, str]:
    """Returns (max-DD-pct, message)."""
    if not equity_curve:
        return Decimal("0"), "(empty)"
    peak = equity_curve[0][1]
    max_dd = Decimal("0")
    peak_ts = equity_curve[0][0]
    trough_ts = equity_curve[0][0]
    for ts, eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else Decimal("0")
        if dd > max_dd:
            max_dd = dd
            trough_ts = ts
            for p_ts, p_eq in equity_curve:
                if p_eq == peak:
                    peak_ts = p_ts
                    break
    return max_dd, f"peak {peak_ts.date()} -> trough {trough_ts.date()}"


def longest_losing_streak(trades_pnl: list) -> int:
    streak = 0
    max_streak = 0
    for p in trades_pnl:
        if p <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def report(label: str, final_eq, trades_pnl, curve):
    wins = sum(1 for p in trades_pnl if p > 0)
    n = len(trades_pnl)
    print(f"\n  {label}:")
    if n == 0:
        print("    no trades")
        return
    win_rate = wins / n * 100
    net_return = (final_eq - Decimal("1000")) / Decimal("1000") * 100
    avg_trade = sum(trades_pnl, Decimal("0")) / Decimal(n)
    worst = min(trades_pnl)
    best = max(trades_pnl)
    dd, dd_msg = max_drawdown(curve)
    streak = longest_losing_streak(trades_pnl)
    print(f"    trades         {n}")
    print(f"    win-rate       {win_rate:.1f}%")
    print(f"    net return     {float(net_return):+.2f}%")
    print(f"    avg trade      {float(avg_trade):+.3f} USDT")
    print(f"    worst trade    {float(worst):+.3f} USDT")
    print(f"    best trade     {float(best):+.3f} USDT")
    print(f"    max drawdown   {float(dd)*100:.2f}%  ({dd_msg})")
    print(f"    longest losing streak {streak} trades")


def main():
    bars = load("SOLUSDT", "4H")
    if not bars:
        print("No SOL data. Run pull first.")
        return
    # Split: last 6 months = OOS, rest = IS
    cutoff_idx = len(bars) - 6 * 30 * 6  # 6 months × 30 days × 6 bars/day
    is_bars = bars[:cutoff_idx]
    oos_bars = bars[cutoff_idx - 60:]  # include 60-bar warmup for indicators

    print("=" * 78)
    print("SOL-only Breakout: HOLD-OUT VALIDATION + DRAWDOWN")
    print("=" * 78)
    print(f"Total bars: {len(bars)}")
    print(f"In-sample:   {is_bars[0].ts.date()} .. {is_bars[-1].ts.date()}  ({len(is_bars)} bars)")
    print(f"Out-of-sample: {oos_bars[0].ts.date()} .. {oos_bars[-1].ts.date()}  ({len(oos_bars)} bars)")
    print()
    print("Filter: vol-1.5x + confirm-2 + RSI-55 (locked from IS analysis)")

    # In-sample
    final_is, tr_is, curve_is = run_with_equity_curve(is_bars)
    report("IN-SAMPLE (18 months, used to pick filter)", final_is, tr_is, curve_is)

    # Out-of-sample
    final_oos, tr_oos, curve_oos = run_with_equity_curve(oos_bars)
    report("OUT-OF-SAMPLE (6 months, truly unseen)", final_oos, tr_oos, curve_oos)

    print()
    print("=" * 78)
    print("VERDICT:")
    if not tr_oos:
        print("  OOS no trades. Cannot confirm edge.")
    elif sum(tr_oos, Decimal("0")) > 0:
        print("  OOS POSITIVE. Edge survives unseen data. Cautiously proceed to Phase 5.")
    else:
        print("  OOS NEGATIVE. Edge does not survive unseen data. STOP.")
    print("=" * 78)


if __name__ == "__main__":
    main()

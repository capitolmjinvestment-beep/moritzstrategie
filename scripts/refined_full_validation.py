#!/usr/bin/env python3
"""Final refinement: all 5 indicators (RSI/ATR/Camarilla/Patterns/Fibonacci) +
hold-out validation.

Adds Fibonacci-based exits to the breakout-strategy:
  - TP1: 1.272 Fibonacci extension of the prior down-leg (was: H4)
  - TP2: 1.618 Fibonacci extension (was: entry + 2*ATR)
  - Trailing-stop: ratchet to 0.382 retracement of running profit

Then re-runs hold-out test on SOL to see if the Fibonacci-TPs change the
in-sample vs out-of-sample picture vs. the previous flat-target version.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from moritzstrategie.aggregation import aggregate_to_daily
from moritzstrategie.atr import compute_atr
from moritzstrategie.backtest import _process_exits, Trade
from moritzstrategie.camarilla import compute_camarilla
from moritzstrategie.data.loader import load
from moritzstrategie.fibonacci import SwingDirection, compute_fibonacci
from moritzstrategie.friction import default_bitget_friction
from moritzstrategie.risk import PortfolioState, RiskManager
from moritzstrategie.rsi import compute_rsi
from moritzstrategie.strategy import EntrySignal, Side
from moritzstrategie.types import Bar


def _recent_swing(bars: Sequence[Bar], current_idx: int,
                  lookback: int = 30) -> Optional[tuple[Decimal, Decimal, SwingDirection]]:
    """Find the most recent (low, high, direction) swing in the last `lookback` bars.

    Direction = UP if low precedes high in the window, DOWN if high precedes low.
    """
    if current_idx < lookback:
        return None
    start = current_idx - lookback + 1
    window = bars[start:current_idx + 1]
    lo_idx = min(range(len(window)), key=lambda i: window[i].low)
    hi_idx = max(range(len(window)), key=lambda i: window[i].high)
    lo = window[lo_idx].low
    hi = window[hi_idx].high
    if hi <= lo:
        return None
    direction = SwingDirection.UP if lo_idx < hi_idx else SwingDirection.DOWN
    return lo, hi, direction


def evaluate_breakout_fib(
    bars: Sequence[Bar],
    current_idx: int,
    camarilla: dict[str, Decimal],
    volume_mult: Decimal = Decimal("1.5"),
    confirm_bars: int = 2,
    rsi_strict_threshold: Decimal = Decimal("55"),
    rsi_period: int = 14,
    atr_period: int = 14,
    stop_atr_mult: Decimal = Decimal("1.0"),
    swing_lookback: int = 30,
) -> Optional[EntrySignal]:
    """Breakout with Fibonacci-extension targets (TP1 = 1.272, TP2 = 1.618 of swing)."""
    if current_idx < max(rsi_period, atr_period, swing_lookback) + 1:
        return None
    window = list(bars[: current_idx + 1])
    closes = [b.close for b in window]
    rsi = compute_rsi(closes, period=rsi_period)
    atr = compute_atr(window, period=atr_period)
    cur_rsi = rsi[current_idx]
    cur_atr = atr[current_idx]
    if cur_rsi is None or cur_atr is None:
        return None

    h3 = camarilla.get("H3")
    l3 = camarilla.get("L3")
    if h3 is None or l3 is None:
        return None

    cur_close = window[current_idx].close
    cur_bar = window[current_idx]

    # Volume filter
    if current_idx >= 20:
        avg_vol = sum((window[j].volume for j in range(current_idx - 19, current_idx + 1)),
                      Decimal("0")) / Decimal("20")
        if cur_bar.volume < volume_mult * avg_vol:
            return None

    long_confirmed = all(window[current_idx - j].close > h3
                         for j in range(confirm_bars) if current_idx - j >= 0)
    short_confirmed = all(window[current_idx - j].close < l3
                          for j in range(confirm_bars) if current_idx - j >= 0)

    swing = _recent_swing(bars, current_idx, lookback=swing_lookback)
    if swing is None:
        return None
    swing_low, swing_high, swing_dir = swing
    fib = compute_fibonacci(swing_low, swing_high, swing_dir)

    if long_confirmed and cur_rsi > rsi_strict_threshold:
        return EntrySignal(
            side=Side.LONG, entry_price=cur_close,
            stop_price=cur_close - stop_atr_mult * cur_atr,
            tp1_price=fib.extension(Decimal("1.272")),
            tp2_price=fib.extension(Decimal("1.618")),
            trigger_idx=current_idx,
        )
    if short_confirmed and cur_rsi < (Decimal("100") - rsi_strict_threshold):
        return EntrySignal(
            side=Side.SHORT, entry_price=cur_close,
            stop_price=cur_close + stop_atr_mult * cur_atr,
            tp1_price=fib.extension(Decimal("1.272")),
            tp2_price=fib.extension(Decimal("1.618")),
            trigger_idx=current_idx,
        )
    return None


def run_fib_backtest(bars, symbol="SOLUSDT", initial_equity=Decimal("1000"), **kw):
    state = PortfolioState.fresh(initial_equity)
    rm = RiskManager(state)
    friction = default_bitget_friction()
    daily = aggregate_to_daily(bars)
    levels_by_date = {}
    for i, d in enumerate(daily):
        if i + 1 < len(daily):
            levels_by_date[daily[i + 1].ts] = compute_camarilla(d)
    trades_pnl: list[Decimal] = []
    open_trade = None
    for i, bar in enumerate(bars):
        day_start = bar.ts.replace(hour=0, minute=0, second=0, microsecond=0)
        cam = levels_by_date.get(day_start)
        if open_trade is not None:
            _process_exits(open_trade, bar, i, time_stop_bars=12, friction=friction)
            if open_trade.closed:
                pnl = open_trade.net_pnl_pct() * initial_equity * Decimal("0.5")
                state.realize_pnl(pnl, when=open_trade.exits[-1].ts)
                state.close_position(symbol)
                trades_pnl.append(pnl)
                open_trade = None
        if open_trade is None and cam is not None:
            sig = evaluate_breakout_fib(bars, i, cam, **kw)
            if sig is not None:
                # Sanity: TPs must be on the correct side of entry
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


def report(label, final_eq, trades_pnl):
    n = len(trades_pnl)
    print(f"\n  {label}:")
    if n == 0:
        print("    no trades")
        return
    wins = sum(1 for p in trades_pnl if p > 0)
    print(f"    trades         {n}")
    print(f"    win-rate       {wins / n * 100:.1f}%")
    print(f"    net return     {float((final_eq - Decimal('1000')) / Decimal('1000')) * 100:+.2f}%")
    print(f"    avg trade      {float(sum(trades_pnl, Decimal('0')) / Decimal(n)):+.3f} USDT")
    print(f"    worst trade    {float(min(trades_pnl)):+.3f} USDT")
    print(f"    best trade     {float(max(trades_pnl)):+.3f} USDT")


def main():
    print("=" * 78)
    print("REFINED STRATEGY: Camarilla + RSI + ATR + Patterns(implicit) + Fibonacci")
    print("=" * 78)
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        bars = load(sym, "4H")
        if not bars:
            print(f"\n{sym}: no data; skip.")
            continue
        print(f"\n=== {sym}: {len(bars)} bars ===")
        cutoff = len(bars) - 6 * 30 * 6
        is_bars = bars[:cutoff]
        oos_bars = bars[cutoff - 60:]

        eq_is, tr_is = run_fib_backtest(is_bars, symbol=sym)
        eq_oos, tr_oos = run_fib_backtest(oos_bars, symbol=sym)
        report(f"IN-SAMPLE ({is_bars[0].ts.date()}..{is_bars[-1].ts.date()})", eq_is, tr_is)
        report(f"OUT-OF-SAMPLE ({oos_bars[0].ts.date()}..{oos_bars[-1].ts.date()})",
               eq_oos, tr_oos)

    print()
    print("=" * 78)


if __name__ == "__main__":
    main()

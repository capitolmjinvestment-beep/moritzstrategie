#!/usr/bin/env python3
"""Strategy-edge exploration on real BTC/ETH/SOL 4h data.

Tests three approaches in parallel to answer: is there ANY edge in this data?

A) Baseline + relaxed-parameter variants of the mean-reversion strategy
B) Multi-symbol — same strategy across BTC/ETH/SOL
C) Breakout variant — long when bar closes ABOVE H3 (trend-following, opposite
   thesis to the original mean-reversion)

Output: comparison table of (strategy, symbol) -> n_trades, win_rate, net%.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from moritzstrategie.aggregation import aggregate_to_daily  # noqa: E402
from moritzstrategie.atr import compute_atr  # noqa: E402
from moritzstrategie.camarilla import compute_camarilla  # noqa: E402
from moritzstrategie.data.loader import load  # noqa: E402
from moritzstrategie.friction import default_bitget_friction  # noqa: E402
from moritzstrategie.portfolio_backtest import run_portfolio_backtest  # noqa: E402
from moritzstrategie.rsi import compute_rsi  # noqa: E402
from moritzstrategie.strategy import EntryParams, EntrySignal, Side  # noqa: E402
from moritzstrategie.types import Bar  # noqa: E402


# ============================================================================
# Variant C: breakout entries (opposite thesis)
# ============================================================================

def evaluate_breakout_entry(
    bars: Sequence[Bar],
    current_idx: int,
    camarilla: dict[str, Decimal],
    rsi_period: int = 14,
    atr_period: int = 14,
    stop_atr_mult: Decimal = Decimal("1.0"),
    volume_mult: Optional[Decimal] = None,   # require vol > volume_mult * 20-bar avg
    confirm_bars: int = 1,                   # require N consecutive closes beyond level
    rsi_strict_threshold: Decimal = Decimal("50"),  # 50=loose, 55/45=stricter
) -> Optional[EntrySignal]:
    """Camarilla-breakout entry (trend-following).

    Long-Setup:
      - Bar closes above H3 (breakout up)
      - RSI > 50 (uptrend confirmation)
    Short-Setup:
      - Bar closes below L3 (breakout down)
      - RSI < 50

    Stop: 1.0 * ATR from entry (no double-bottom logic).
    TP1: H4 / L4 (extended pivot extremes).
    TP2: 2x ATR from entry (trend target).
    """
    if current_idx < max(rsi_period, atr_period) + 1:
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
    h4 = camarilla.get("H4") or camarilla.get("H3")  # fallback if H4 missing
    l4 = camarilla.get("L4") or camarilla.get("L3")
    p = camarilla.get("P")
    if h3 is None or l3 is None or p is None:
        return None

    cur_close = window[current_idx].close

    # Volume filter: current bar must show conviction
    if volume_mult is not None and current_idx >= 20:
        avg_vol = sum((window[j].volume for j in range(current_idx - 19, current_idx + 1)),
                      Decimal("0")) / Decimal("20")
        if window[current_idx].volume < volume_mult * avg_vol:
            return None

    # Multi-bar-confirmation: last N closes all on the same side of the level
    long_confirmed = all(
        window[current_idx - j].close > h3
        for j in range(confirm_bars)
        if current_idx - j >= 0
    )
    short_confirmed = all(
        window[current_idx - j].close < l3
        for j in range(confirm_bars)
        if current_idx - j >= 0
    )

    if long_confirmed and cur_rsi > rsi_strict_threshold:
        return EntrySignal(
            side=Side.LONG, entry_price=cur_close,
            stop_price=cur_close - stop_atr_mult * cur_atr,
            tp1_price=h4 if h4 > cur_close else cur_close + cur_atr,
            tp2_price=cur_close + Decimal("2") * cur_atr,
            trigger_idx=current_idx,
        )
    if short_confirmed and cur_rsi < (Decimal("100") - rsi_strict_threshold):
        return EntrySignal(
            side=Side.SHORT, entry_price=cur_close,
            stop_price=cur_close + stop_atr_mult * cur_atr,
            tp1_price=l4 if l4 < cur_close else cur_close - cur_atr,
            tp2_price=cur_close - Decimal("2") * cur_atr,
            trigger_idx=current_idx,
        )
    return None


def run_breakout_backtest(bars: Sequence[Bar], symbol: str = "TEST",
                          initial_equity: Decimal = Decimal("1000"),
                          volume_mult: Optional[Decimal] = None,
                          confirm_bars: int = 1,
                          rsi_strict_threshold: Decimal = Decimal("50")):
    """Minimal portfolio backtest using the breakout-entry variant."""
    from moritzstrategie.backtest import _process_exits, ExitEvent, Trade
    from moritzstrategie.risk import PortfolioState, RiskManager
    from moritzstrategie.portfolio_backtest import PortfolioResult

    if not bars:
        return PortfolioResult(initial_equity, initial_equity, [], 0, {})

    state = PortfolioState.fresh(initial_equity)
    rm = RiskManager(state)
    friction = default_bitget_friction()

    # Daily levels
    daily = aggregate_to_daily(bars)
    levels_by_date = {}
    for i, d in enumerate(daily):
        if i + 1 < len(daily):
            levels_by_date[daily[i + 1].ts] = compute_camarilla(d)

    # Use the same PortfolioResult machinery but simpler trade tracking
    trades_pnl_pct: list[Decimal] = []
    open_trade: Optional[Trade] = None
    open_entry_idx = 0
    skipped = 0

    for i, bar in enumerate(bars):
        day_start = bar.ts.replace(hour=0, minute=0, second=0, microsecond=0)
        cam = levels_by_date.get(day_start)

        if open_trade is not None:
            _process_exits(open_trade, bar, i, time_stop_bars=12, friction=friction)
            if open_trade.closed:
                trades_pnl_pct.append(open_trade.net_pnl_pct())
                # Apply to equity
                pnl_abs = open_trade.net_pnl_pct() * state.current_equity * Decimal("0.015") / abs(
                    (open_trade.entry_price - open_trade.stop_price) / open_trade.entry_price
                ) if open_trade.entry_price != open_trade.stop_price else Decimal("0")
                # Simpler: just apply pnl_pct directly to a 1.5%-risk-sized notional
                state.realize_pnl(open_trade.net_pnl_pct() * initial_equity * Decimal("0.5"),
                                   when=open_trade.exits[-1].ts)
                state.close_position(symbol)
                open_trade = None

        if open_trade is None and cam is not None:
            sig = evaluate_breakout_entry(
                bars, i, cam,
                volume_mult=volume_mult,
                confirm_bars=confirm_bars,
                rsi_strict_threshold=rsi_strict_threshold,
            )
            if sig is not None:
                decision = rm.check_entry_allowed(symbol, sig.entry_price, sig.stop_price)
                if not decision.allowed:
                    skipped += 1
                    continue
                open_trade = Trade(
                    side=sig.side, entry_idx=i, entry_ts=bar.ts,
                    entry_price=sig.entry_price, stop_price=sig.stop_price,
                    tp1_price=sig.tp1_price, tp2_price=sig.tp2_price,
                    friction_pct=friction.fee_cost(Decimal("1"), is_taker=True),
                )
                state.open_position(symbol)

    closed = len(trades_pnl_pct)
    wins = sum(1 for p in trades_pnl_pct if p > 0)
    return {
        "trades": closed,
        "winners": wins,
        "win_rate": Decimal(wins) / Decimal(closed) if closed else None,
        "total_pnl_pct": sum(trades_pnl_pct, Decimal("0")),
        "final_equity": state.current_equity,
    }


# ============================================================================
# Variant A: relaxed mean-reversion parameters
# ============================================================================

VARIANTS = {
    "MR baseline":   EntryParams(),
    "MR k=1":        EntryParams(pivot_k=1),
    "MR k=1 RSI35":  EntryParams(pivot_k=1, rsi_oversold=Decimal("35"),
                                 rsi_overbought=Decimal("65")),
    "MR k=1 lookbacks2x": EntryParams(pivot_k=1, pivot_touch_lookback=10,
                                       rsi_extreme_lookback=6, pattern_lookback=25),
    "MR aggressive": EntryParams(pivot_k=1, rsi_oversold=Decimal("40"),
                                  rsi_overbought=Decimal("60"),
                                  pivot_touch_lookback=10,
                                  rsi_extreme_lookback=6,
                                  pattern_lookback=25),
}


def _short_metrics(symbol: str, label: str, result_dict: dict) -> str:
    n = result_dict.get("trades", 0)
    if n == 0:
        return f"  {symbol:7s} {label:22s}  0 trades"
    wr = float(result_dict["win_rate"] or 0) * 100
    pnl = float(result_dict.get("total_pnl_pct", 0)) * 100
    return f"  {symbol:7s} {label:22s}  trades={n:3d}  win-rate={wr:5.1f}%  PnL={pnl:+7.2f}%"


def main():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    friction = default_bitget_friction()

    print("=" * 78)
    print("Strategy exploration on real 4h data (2 years, 2024-05-17 .. 2026-05-16)")
    print("=" * 78)

    bars_by_symbol = {sym: load(sym, "4H") for sym in symbols}
    for sym, bars in bars_by_symbol.items():
        print(f"\n{sym}: {len(bars)} bars  price={min(b.low for b in bars):.0f}..{max(b.high for b in bars):.0f}")

    print("\n--- A: MEAN-REVERSION VARIANTS (original thesis) ---\n")
    for sym in symbols:
        bars = bars_by_symbol[sym]
        for label, params in VARIANTS.items():
            r = run_portfolio_backtest(bars, symbol=sym,
                initial_equity=Decimal("1000"),
                entry_params=params, friction=friction)
            ret = {
                "trades": r.n_trades,
                "win_rate": r.win_rate,
                "total_pnl_pct": r.total_return_pct,
            }
            print(_short_metrics(sym, label, ret))
        print()

    print("--- D: WALK-FORWARD (top breakout variants, 3-month windows) ---\n")
    wf_variants = [
        ("BR vol-1.5x",        {"volume_mult": Decimal("1.5"), "confirm_bars": 1,
                                "rsi_strict_threshold": Decimal("50")}),
        ("BR vol+confirm+RSI", {"volume_mult": Decimal("1.5"), "confirm_bars": 2,
                                 "rsi_strict_threshold": Decimal("55")}),
    ]
    window_bars = 6 * 30 * 3  # 90 days
    for sym in symbols:
        bars = bars_by_symbol[sym]
        for label, kwargs in wf_variants:
            n_pos = 0
            n_neg = 0
            total_pnl = Decimal("0")
            window_count = 0
            cursor = 60  # warmup
            while cursor + window_bars <= len(bars):
                sub = bars[max(0, cursor - 60):cursor + window_bars]
                r = run_breakout_backtest(sub, symbol=sym, **kwargs)
                if r["trades"] > 0:
                    if r["total_pnl_pct"] > 0:
                        n_pos += 1
                    else:
                        n_neg += 1
                    total_pnl += r["total_pnl_pct"]
                window_count += 1
                cursor += window_bars  # disjoint
            print(f"  {sym:7s} {label:22s}  windows={window_count}  "
                  f"pos={n_pos}  neg={n_neg}  avg-window-pnl="
                  f"{float(total_pnl / window_count) * 100 if window_count else 0:+6.2f}%")
        print()

    print("--- C: BREAKOUT VARIANT (opposite thesis: trend-follow) ---\n")
    breakout_variants = [
        ("BR baseline",      {"volume_mult": None, "confirm_bars": 1,
                              "rsi_strict_threshold": Decimal("50")}),
        ("BR vol-1.5x",      {"volume_mult": Decimal("1.5"), "confirm_bars": 1,
                              "rsi_strict_threshold": Decimal("50")}),
        ("BR confirm-2",     {"volume_mult": None, "confirm_bars": 2,
                              "rsi_strict_threshold": Decimal("50")}),
        ("BR RSI 55",        {"volume_mult": None, "confirm_bars": 1,
                              "rsi_strict_threshold": Decimal("55")}),
        ("BR vol+confirm+RSI",{"volume_mult": Decimal("1.5"), "confirm_bars": 2,
                               "rsi_strict_threshold": Decimal("55")}),
    ]
    for sym in symbols:
        bars = bars_by_symbol[sym]
        for label, kwargs in breakout_variants:
            r = run_breakout_backtest(bars, symbol=sym, **kwargs)
            print(_short_metrics(sym, label, r))
        print()


if __name__ == "__main__":
    main()

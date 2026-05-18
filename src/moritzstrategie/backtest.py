"""Minimal backtest engine for the H4 Camarilla Reversal strategy.

This is NOT a full backtester (no fees, no slippage model, no funding,
no equity tracking, no multi-symbol). It is a SANITY engine: given a
sequence of bars and an entry function, it produces a list of closed
Trades using the exit rules from MASTERPLAN Section 6.

Use it to:
  - Verify the strategy produces *any* trades on real data (Phase 3 gate)
  - Eyeball trade timing and PnL plausibility
  - Surface look-ahead bugs that escape unit tests

DO NOT use it for production decisions. Real backtest belongs in MjCapital
repo with proper fee/funding/slippage modeling.

Exit-Logik (per MASTERPLAN Section 6):
  - TP1: price reaches central pivot P -> close 50% (tracked as partial fill)
  - TP2 (long): price reaches H3 -> close remaining 50%
  - TP2 (short): price reaches L3 -> close remaining 50%
  - SL (long): price <= stop_price -> close full (or remaining)
  - SL (short): price >= stop_price -> close full (or remaining)
  - Time-Stop: 12 bars (48h) after entry without TP2/SL -> close at market (next open)

Conflict resolution within a bar: if a bar's range contains both stop AND tp,
we assume STOP fills first (conservative). Real fill order depends on intra-bar
price path which we don't have at 4h granularity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Callable, Optional, Sequence

from .aggregation import aggregate_to_daily
from .camarilla import compute_camarilla
from .friction import FrictionModel
from .strategy import EntryParams, EntrySignal, Side, evaluate_entry
from .types import Bar


@dataclass(frozen=True)
class ExitEvent:
    reason: str  # 'tp1', 'tp2', 'stop', 'time_stop'
    price: Decimal
    idx: int
    ts: datetime


@dataclass
class Trade:
    side: Side
    entry_idx: int
    entry_ts: datetime
    entry_price: Decimal
    stop_price: Decimal
    tp1_price: Decimal
    tp2_price: Decimal
    exits: list[ExitEvent] = field(default_factory=list)
    # Accumulated friction (fees + funding) as fraction of notional.
    # 0 by default; populated by run_backtest only if friction is provided.
    # Slippage is applied at the price level (entry_price + exit prices already adjusted)
    # so it's reflected in pnl_pct directly, not in this field.
    friction_pct: Decimal = field(default_factory=lambda: Decimal("0"))

    @property
    def closed(self) -> bool:
        # Closed if last exit is stop/tp2/time_stop, or if both tp1+tp2 fired
        if not self.exits:
            return False
        last = self.exits[-1].reason
        if last in ("stop", "tp2", "time_stop"):
            return True
        reasons = {e.reason for e in self.exits}
        return "tp1" in reasons and "tp2" in reasons

    def pnl_pct(self) -> Decimal:
        """Realized PnL as a percentage of entry price.

        Assumes 50/50 split between TP1 and TP2. If only one exit fires
        (e.g., stop before tp1), full position exits at that level.
        """
        if not self.exits:
            return Decimal("0")
        if self.entry_price <= Decimal("0"):
            # Should be impossible (Bar validation rejects zero prices), but guard anyway.
            raise ValueError(f"Trade.entry_price must be > 0, got {self.entry_price}")
        sign = Decimal("1") if self.side == Side.LONG else Decimal("-1")

        # Single-exit scenarios: stop or time_stop before tp1 -> full at that price
        if len(self.exits) == 1 and self.exits[0].reason != "tp1":
            ex = self.exits[0]
            return sign * (ex.price - self.entry_price) / self.entry_price

        # Otherwise: 50% at each leg
        pnl = Decimal("0")
        portions = [Decimal("0.5"), Decimal("0.5")]
        for ex, frac in zip(self.exits, portions):
            pnl += frac * sign * (ex.price - self.entry_price) / self.entry_price
        return pnl

    def net_pnl_pct(self) -> Decimal:
        """Gross PnL minus accumulated friction (fees + funding).

        Slippage is already in pnl_pct via adjusted entry/exit prices.
        """
        return self.pnl_pct() - self.friction_pct


def run_backtest(
    bars: Sequence[Bar],
    entry_params: EntryParams = EntryParams(),
    time_stop_bars: int = 12,
    daily_levels_provider: Optional[Callable[[datetime], Optional[dict[str, Decimal]]]] = None,
    friction: Optional[FrictionModel] = None,
) -> list[Trade]:
    """Run the strategy over `bars` and return all trades.

    Args:
        bars: 4h bars ascending by time. Should cover at least 30 days for
            meaningful results.
        entry_params: Strategy thresholds.
        time_stop_bars: Bars after entry before forced exit (default 12 = 48h).
        daily_levels_provider: Optional callable that maps a UTC date (00:00) to
            Camarilla levels. If None, computed from `bars` via aggregate_to_daily.
        friction: Optional fees+funding+slippage model. If provided:
            - Entry/exit prices are slippage-adjusted (worse fills)
            - Each Trade.friction_pct accumulates fee + funding costs as
              fraction of notional. Use Trade.net_pnl_pct() for net return.

    Returns:
        List of all closed Trades (and the open one, if any, at end of data).
        Note: only 1 open position at a time; new entries blocked while in position.
    """
    if not bars:
        return []

    # Pre-compute daily levels for the entire history (avoids re-aggregating per bar)
    if daily_levels_provider is None:
        daily_bars = aggregate_to_daily(bars)
        levels_by_date: dict[datetime, dict[str, Decimal]] = {}
        for i, daily in enumerate(daily_bars):
            if i + 1 < len(daily_bars):
                # Levels for day[i+1] use day[i] (yesterday's bar)
                next_day_start = daily_bars[i + 1].ts
                levels_by_date[next_day_start] = compute_camarilla(daily)
        def provider(day_start: datetime) -> Optional[dict[str, Decimal]]:
            return levels_by_date.get(day_start)
    else:
        provider = daily_levels_provider

    trades: list[Trade] = []
    open_trade: Optional[Trade] = None

    for i, bar in enumerate(bars):
        day_start = bar.ts.replace(hour=0, minute=0, second=0, microsecond=0)
        cam = provider(day_start)

        # ---- Exit logic for open trade ----
        if open_trade is not None:
            _process_exits(open_trade, bar, i, time_stop_bars, friction=friction)
            if open_trade.closed:
                # Funding cost on close: charge for hours actually held
                if friction is not None and open_trade.exits:
                    hours_held = Decimal(
                        str((open_trade.exits[-1].ts - open_trade.entry_ts).total_seconds() / 3600)
                    )
                    open_trade.friction_pct += (
                        friction.funding_cost(Decimal("1"), hours_held, open_trade.side)
                    )
                trades.append(open_trade)
                open_trade = None

        # ---- Entry logic (only if flat) ----
        if open_trade is None and cam is not None:
            sig = evaluate_entry(bars, i, cam, params=entry_params)
            if sig is not None:
                entry_px = sig.entry_price
                friction_pct = Decimal("0")
                if friction is not None:
                    # Need ATR for slippage; cheap approximation: use bar's range
                    bar_range = bar.high - bar.low
                    entry_px = friction.apply_entry_slippage(
                        sig.side, sig.entry_price, atr=bar_range
                    )
                    # Entry-leg fee (notional=1 for fraction-of-notional accounting)
                    friction_pct += friction.fee_cost(Decimal("1"), is_taker=True)
                open_trade = Trade(
                    side=sig.side,
                    entry_idx=i,
                    entry_ts=bar.ts,
                    entry_price=entry_px,
                    stop_price=sig.stop_price,
                    tp1_price=sig.tp1_price,
                    tp2_price=sig.tp2_price,
                    friction_pct=friction_pct,
                )

    # If a trade is still open at end of data, include it for inspection
    if open_trade is not None:
        trades.append(open_trade)
    return trades


def _process_exits(
    trade: Trade,
    bar: Bar,
    idx: int,
    time_stop_bars: int,
    friction: Optional[FrictionModel] = None,
) -> None:
    """Mutate `trade` by appending any exit events triggered by this bar.

    If `friction` is provided, exit prices are slippage-adjusted and the
    exit-leg fee is added to `trade.friction_pct` (split across TP1/TP2 legs).
    """
    if trade.closed:
        return

    bars_held = idx - trade.entry_idx
    if bars_held == 0:
        return

    tp1_hit = "tp1" in {e.reason for e in trade.exits}
    tp2_hit = "tp2" in {e.reason for e in trade.exits}

    def adj(raw: Decimal) -> Decimal:
        """Apply exit slippage if friction set; ATR proxy = bar's true range."""
        if friction is None:
            return raw
        bar_range = bar.high - bar.low
        return friction.apply_exit_slippage(trade.side, raw, atr=bar_range)

    def charge_exit_fee(fraction_closed: Decimal) -> None:
        """Charge taker fee on the closed fraction of notional."""
        if friction is None:
            return
        trade.friction_pct += friction.fee_cost(fraction_closed, is_taker=True)

    if trade.side == Side.LONG:
        if bar.low <= trade.stop_price:
            # If we already partially closed at TP1, stop closes remaining 50%
            remaining = Decimal("0.5") if tp1_hit else Decimal("1")
            trade.exits.append(ExitEvent("stop", adj(trade.stop_price), idx, bar.ts))
            charge_exit_fee(remaining)
            return
        if not tp1_hit and bar.high >= trade.tp1_price:
            trade.exits.append(ExitEvent("tp1", adj(trade.tp1_price), idx, bar.ts))
            charge_exit_fee(Decimal("0.5"))
            tp1_hit = True
        if tp1_hit and not tp2_hit and bar.high >= trade.tp2_price:
            trade.exits.append(ExitEvent("tp2", adj(trade.tp2_price), idx, bar.ts))
            charge_exit_fee(Decimal("0.5"))
            return
    else:  # SHORT
        if bar.high >= trade.stop_price:
            remaining = Decimal("0.5") if tp1_hit else Decimal("1")
            trade.exits.append(ExitEvent("stop", adj(trade.stop_price), idx, bar.ts))
            charge_exit_fee(remaining)
            return
        if not tp1_hit and bar.low <= trade.tp1_price:
            trade.exits.append(ExitEvent("tp1", adj(trade.tp1_price), idx, bar.ts))
            charge_exit_fee(Decimal("0.5"))
            tp1_hit = True
        if tp1_hit and not tp2_hit and bar.low <= trade.tp2_price:
            trade.exits.append(ExitEvent("tp2", adj(trade.tp2_price), idx, bar.ts))
            charge_exit_fee(Decimal("0.5"))
            return

    if bars_held >= time_stop_bars and not trade.closed:
        remaining = Decimal("0.5") if tp1_hit else Decimal("1")
        trade.exits.append(ExitEvent("time_stop", adj(bar.close), idx, bar.ts))
        charge_exit_fee(remaining)


def summarize(trades: list[Trade]) -> dict[str, object]:
    """Quick stats for a trade list. Not a full tearsheet."""
    closed = [t for t in trades if t.closed]
    if not closed:
        return {"trades": 0, "winners": 0, "losers": 0, "win_rate": None,
                "total_pnl_pct": Decimal("0"), "open": len(trades)}
    pnls = [t.pnl_pct() for t in closed]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p <= 0]
    return {
        "trades": len(closed),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": Decimal(len(winners)) / Decimal(len(closed)),
        "total_pnl_pct": sum(pnls, start=Decimal("0")),
        "avg_pnl_pct": sum(pnls, start=Decimal("0")) / Decimal(len(closed)),
        "best": max(pnls),
        "worst": min(pnls),
        "open": len(trades) - len(closed),
    }

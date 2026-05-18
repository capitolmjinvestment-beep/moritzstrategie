#!/usr/bin/env python3
"""Compare gross vs. net backtest results to show how much friction eats.

Two runs over the same synthetic data:
  1. No friction (raw strategy edge)
  2. Default Bitget friction (6bps taker fee + 0.01%/8h funding + 5bps constant slippage)

The delta is what your real PnL would lose to the exchange + market mechanics.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from moritzstrategie.backtest import run_backtest, summarize  # noqa: E402
from moritzstrategie.friction import (  # noqa: E402
    BitgetTakerFee,
    ConstantSlippage,
    FrictionModel,
    PeriodicFunding,
    VolatilitySlippage,
    default_bitget_friction,
)
from scripts.run_backtest import synthetic_bars  # noqa: E402


def _summary_line(label: str, trades: list) -> None:
    closed = [t for t in trades if t.closed]
    if not closed:
        print(f"  {label:<25} no trades")
        return
    gross = sum((t.pnl_pct() for t in closed), start=Decimal("0"))
    net = sum((t.net_pnl_pct() for t in closed), start=Decimal("0"))
    friction = sum((t.friction_pct for t in closed), start=Decimal("0"))
    print(f"  {label:<25} trades={len(closed):3d}  "
          f"gross={float(gross)*100:+7.2f}%  "
          f"friction={float(friction)*100:+6.2f}%  "
          f"net={float(net)*100:+7.2f}%")


def _isolated_trade_demo() -> None:
    """Construct ONE realistic LONG trade and compare net PnL across friction models.

    Scenario: BTC at $60000, enters long, TP1 at $61500 (+2.5%), TP2 at $63000 (+5%).
    Both targets hit. Trade held 32h (= 8 4h-bars).
    """
    from datetime import datetime, timedelta, timezone
    from moritzstrategie.backtest import ExitEvent, Trade
    from moritzstrategie.strategy import Side

    UTC = timezone.utc
    entry_ts = datetime(2025, 6, 1, 12, tzinfo=UTC)
    exit_ts = entry_ts + timedelta(hours=32)

    def make_trade(friction):
        entry_px = Decimal("60000")
        if friction is not None:
            entry_px = friction.apply_entry_slippage(Side.LONG, entry_px, atr=Decimal("600"))
        trade = Trade(
            side=Side.LONG, entry_idx=0, entry_ts=entry_ts,
            entry_price=entry_px,
            stop_price=Decimal("58800"),
            tp1_price=Decimal("61500"),
            tp2_price=Decimal("63000"),
        )
        if friction is not None:
            trade.friction_pct = friction.fee_cost(Decimal("1"), is_taker=True)
        # Simulate both TP1 and TP2 hit, with exit slippage
        tp1_px = Decimal("61500")
        tp2_px = Decimal("63000")
        if friction is not None:
            tp1_px = friction.apply_exit_slippage(Side.LONG, tp1_px, atr=Decimal("600"))
            tp2_px = friction.apply_exit_slippage(Side.LONG, tp2_px, atr=Decimal("600"))
            trade.friction_pct += friction.fee_cost(Decimal("0.5"), is_taker=True) * 2
            hours = Decimal("32")
            trade.friction_pct += friction.funding_cost(Decimal("1"), hours, Side.LONG)
        trade.exits = [
            ExitEvent("tp1", tp1_px, 4, entry_ts + timedelta(hours=16)),
            ExitEvent("tp2", tp2_px, 8, exit_ts),
        ]
        return trade

    print("\nIsolated trade: BTC long @ $60000, TP1 hit @ $61500, TP2 hit @ $63000, held 32h\n")
    print(f"  {'scenario':<25} {'gross':>10}  {'friction':>10}  {'net':>10}")
    print(f"  {'-'*25} {'-'*10}  {'-'*10}  {'-'*10}")

    for label, fr in [
        ("no friction (theory)", None),
        ("bitget default", default_bitget_friction()),
        ("stress (2x fee + vol)", FrictionModel(
            fees=BitgetTakerFee(taker_bps=Decimal("12")),
            funding=PeriodicFunding(avg_rate_per_period=Decimal("0.0003")),
            slippage=VolatilitySlippage(alpha=Decimal("0.15"), cap_bps=Decimal("30")),
        )),
        ("maker-fee dream", FrictionModel(
            fees=BitgetTakerFee(taker_bps=Decimal("2")),
            funding=PeriodicFunding(avg_rate_per_period=Decimal("0.0001")),
            slippage=ConstantSlippage(bps=Decimal("0")),
        )),
    ]:
        t = make_trade(fr)
        gross = float(t.pnl_pct()) * 100
        friction = float(t.friction_pct) * 100
        net = float(t.net_pnl_pct()) * 100
        print(f"  {label:<25} {gross:>+9.3f}%  {friction:>+9.3f}%  {net:>+9.3f}%")


def main() -> None:
    bars = synthetic_bars(n_days=365)
    print(f"\nbars: {len(bars)} (1 year of 4h synthetic data)")
    print("(Note: 0 trades on synthetic data is expected - the strategy is conservative.)\n")

    trades_raw = run_backtest(bars, friction=None)
    _summary_line("no friction", trades_raw)
    trades_default = run_backtest(bars, friction=default_bitget_friction())
    _summary_line("bitget default", trades_default)

    _isolated_trade_demo()

    print("\nReadings:")
    print("  - gross > 0 only means the *signal* has positive expectancy")
    print("  - net is what you actually keep")
    print("  - if friction > 0.5 × gross, your edge is fragile against fee changes")
    print("  - dream scenario assumes 100% maker fills (rare in practice)")


if __name__ == "__main__":
    main()

"""Portfolio-level backtest: composes Strategy + Friction + RiskManager.

Where `run_backtest` answers "what trades would the signal produce on this data?",
`run_portfolio_backtest` answers "what would my account look like at the end?"

Key differences from run_backtest:
  - Tracks equity over time (not just per-trade pct returns)
  - Respects RiskManager kill-switches (skips entries when blocked)
  - Position sizing via risk-per-trade formula (notional from equity)
  - Single-symbol only (multi-symbol needs a different orchestrator that
    interleaves bars from multiple symbols by timestamp)

Use this to answer "would I have survived 2022's bear market?" or "does
the daily kill-switch save me on a -20% week?" — questions that per-trade
percentage returns can't capture.

NOT included (still production gaps):
  - Multi-symbol coordination (would need a multi-stream bar feeder)
  - Per-bar mark-to-market equity (only realized PnL is tracked)
  - Margin call / liquidation simulation (assumed never hit; for 3x leverage
    on conservative position sizing this is realistic)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from .aggregation import aggregate_to_daily
from .camarilla import compute_camarilla
from .friction import FrictionModel
from .risk import PortfolioState, RiskManager, RiskParams
from .strategy import EntryParams, Side, evaluate_entry
from .types import Bar


@dataclass
class PortfolioTrade:
    """A trade that actually got placed (passed risk-check)."""
    side: Side
    symbol: str
    entry_idx: int
    entry_ts: datetime
    exit_ts: datetime
    entry_price: Decimal
    exit_price: Decimal           # weighted-average exit (handles TP1+TP2 splits)
    qty: Decimal                  # base-currency units
    notional: Decimal             # qty * entry_price (USDT)
    gross_pnl: Decimal            # in USDT, sign-aware
    friction_cost: Decimal        # in USDT (fees + funding + slippage already in prices)
    net_pnl: Decimal              # gross_pnl - friction_cost
    exits: list[str] = field(default_factory=list)  # ordered exit reasons


@dataclass
class PortfolioResult:
    """Output of a single-symbol portfolio backtest."""
    initial_equity: Decimal
    final_equity: Decimal
    trades: list[PortfolioTrade]
    skipped_signals: int          # signals that fired but risk-check blocked
    skip_reasons: dict[str, int]  # reason -> count

    @property
    def total_return_pct(self) -> Decimal:
        return (self.final_equity - self.initial_equity) / self.initial_equity

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> Optional[Decimal]:
        if not self.trades:
            return None
        wins = sum(1 for t in self.trades if t.net_pnl > 0)
        return Decimal(wins) / Decimal(len(self.trades))


def run_portfolio_backtest(
    bars: Sequence[Bar],
    symbol: str = "TEST",
    initial_equity: Decimal = Decimal("1000"),
    entry_params: EntryParams = EntryParams(),
    risk_params: RiskParams = RiskParams(),
    friction: Optional[FrictionModel] = None,
    time_stop_bars: int = 12,
) -> PortfolioResult:
    """Single-symbol portfolio backtest with risk-aware sizing.

    Walks bars forward, evaluates entry signal each bar (when flat),
    asks RiskManager if entry is allowed, sizes position via 1.5% risk formula,
    holds until TP1/TP2/Stop/TimeStop, accumulates realized PnL into equity.

    Returns a PortfolioResult with the full trade list, skip stats, and equity.
    """
    if not bars:
        return PortfolioResult(initial_equity, initial_equity, [], 0, {})

    state = PortfolioState.fresh(initial_equity)
    rm = RiskManager(state, risk_params)

    # Pre-compute Camarilla levels by day (same approach as run_backtest)
    daily_bars = aggregate_to_daily(bars)
    levels_by_date: dict[datetime, dict[str, Decimal]] = {}
    for i, d in enumerate(daily_bars):
        if i + 1 < len(daily_bars):
            levels_by_date[daily_bars[i + 1].ts] = compute_camarilla(d)

    trades: list[PortfolioTrade] = []
    skipped = 0
    skip_reasons: dict[str, int] = {}

    open_trade: Optional[dict] = None  # in-flight trade dict (light, mutable)

    for i, bar in enumerate(bars):
        day_start = bar.ts.replace(hour=0, minute=0, second=0, microsecond=0)
        cam = levels_by_date.get(day_start)

        # ---- Exit logic ----
        if open_trade is not None:
            _try_exits(open_trade, bar, i, time_stop_bars, friction)
            if open_trade.get("closed"):
                pt = _finalize(open_trade, bar, symbol, friction)
                # Apply realized PnL to portfolio
                state.realize_pnl(pt.net_pnl, when=pt.exit_ts)
                state.close_position(symbol)
                trades.append(pt)
                open_trade = None

        # ---- Entry logic ----
        if open_trade is None and cam is not None:
            sig = evaluate_entry(bars, i, cam, params=entry_params)
            if sig is not None:
                # Apply entry slippage BEFORE risk-check (sizing uses realistic entry)
                entry_px = sig.entry_price
                if friction is not None:
                    bar_range = bar.high - bar.low
                    entry_px = friction.apply_entry_slippage(sig.side, sig.entry_price, atr=bar_range)
                # Risk check
                decision = rm.check_entry_allowed(symbol, entry_px, sig.stop_price)
                if not decision.allowed:
                    skipped += 1
                    skip_reasons[decision.reason] = skip_reasons.get(decision.reason, 0) + 1
                else:
                    qty = decision.position_qty
                    notional = qty * entry_px
                    # Charge entry fee (in USDT)
                    entry_fee = (friction.fee_cost(notional, is_taker=True)
                                 if friction is not None else Decimal("0"))
                    open_trade = {
                        "side": sig.side,
                        "entry_idx": i,
                        "entry_ts": bar.ts,
                        "entry_price": entry_px,
                        "stop_price": sig.stop_price,
                        "tp1_price": sig.tp1_price,
                        "tp2_price": sig.tp2_price,
                        "qty": qty,
                        "notional": notional,
                        "exits": [],  # list of (reason, price, ts, fraction_closed)
                        "friction_cost": entry_fee,
                    }
                    state.open_position(symbol)

    return PortfolioResult(
        initial_equity=initial_equity,
        final_equity=state.current_equity,
        trades=trades,
        skipped_signals=skipped,
        skip_reasons=skip_reasons,
    )


def _try_exits(
    t: dict, bar: Bar, idx: int, time_stop_bars: int, friction: Optional[FrictionModel]
) -> None:
    """Mutate trade dict by appending exits + accumulating friction."""
    bars_held = idx - t["entry_idx"]
    if bars_held == 0:
        return

    reasons_so_far = {e[0] for e in t["exits"]}
    tp1_hit = "tp1" in reasons_so_far

    def adj(raw: Decimal) -> Decimal:
        if friction is None:
            return raw
        return friction.apply_exit_slippage(t["side"], raw, atr=(bar.high - bar.low))

    def book_exit(reason: str, price: Decimal, frac: Decimal) -> None:
        adjusted = adj(price)
        t["exits"].append((reason, adjusted, bar.ts, frac))
        if friction is not None:
            t["friction_cost"] += friction.fee_cost(t["notional"] * frac, is_taker=True)

    if t["side"] == Side.LONG:
        if bar.low <= t["stop_price"]:
            book_exit("stop", t["stop_price"], Decimal("0.5") if tp1_hit else Decimal("1"))
            t["closed"] = True
            return
        if not tp1_hit and bar.high >= t["tp1_price"]:
            book_exit("tp1", t["tp1_price"], Decimal("0.5"))
            tp1_hit = True
        if tp1_hit and "tp2" not in {e[0] for e in t["exits"]} and bar.high >= t["tp2_price"]:
            book_exit("tp2", t["tp2_price"], Decimal("0.5"))
            t["closed"] = True
            return
    else:  # SHORT
        if bar.high >= t["stop_price"]:
            book_exit("stop", t["stop_price"], Decimal("0.5") if tp1_hit else Decimal("1"))
            t["closed"] = True
            return
        if not tp1_hit and bar.low <= t["tp1_price"]:
            book_exit("tp1", t["tp1_price"], Decimal("0.5"))
            tp1_hit = True
        if tp1_hit and "tp2" not in {e[0] for e in t["exits"]} and bar.low <= t["tp2_price"]:
            book_exit("tp2", t["tp2_price"], Decimal("0.5"))
            t["closed"] = True
            return

    if bars_held >= time_stop_bars and not t.get("closed"):
        book_exit("time_stop", bar.close, Decimal("0.5") if tp1_hit else Decimal("1"))
        t["closed"] = True


def _finalize(
    t: dict, last_bar: Bar, symbol: str, friction: Optional[FrictionModel]
) -> PortfolioTrade:
    """Convert in-flight trade dict to PortfolioTrade + add funding cost."""
    side = t["side"]
    qty = t["qty"]
    entry_price = t["entry_price"]
    # Weighted-average exit price
    total_frac = sum(frac for _, _, _, frac in t["exits"])
    if total_frac > 0:
        weighted_exit = sum(price * frac for _, price, _, frac in t["exits"]) / total_frac
    else:
        weighted_exit = last_bar.close
    sign = Decimal("1") if side == Side.LONG else Decimal("-1")
    gross_pnl = sign * qty * (weighted_exit - entry_price)
    exit_ts = t["exits"][-1][2]

    # Funding cost on close (in USDT)
    friction_cost = t["friction_cost"]
    if friction is not None:
        hours_held = Decimal(str((exit_ts - t["entry_ts"]).total_seconds() / 3600))
        friction_cost += friction.funding_cost(t["notional"], hours_held, side)

    return PortfolioTrade(
        side=side, symbol=symbol,
        entry_idx=t["entry_idx"], entry_ts=t["entry_ts"], exit_ts=exit_ts,
        entry_price=entry_price, exit_price=weighted_exit,
        qty=qty, notional=t["notional"],
        gross_pnl=gross_pnl,
        friction_cost=friction_cost,
        net_pnl=gross_pnl - friction_cost,
        exits=[reason for reason, *_ in t["exits"]],
    )

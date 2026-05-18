"""Risk management: position sizing + kill switches.

Per MASTERPLAN Section 7:
  - Risk per trade: 1.5% of equity
  - Position size: (equity * risk_pct) / |entry - stop|
  - Max 1 open position per symbol
  - Max 2 open positions across all symbols
  - Daily loss kill: stop new entries if today's PnL <= -10% of starting equity
  - Aggregate loss kill: stop new entries if total equity <= 80% of initial

Stateless components where possible (position_size_from_risk is a pure function).
The PortfolioState tracks running equity + position counts and is the only
mutable surface. RiskManager wraps it with the kill-switch + sizing logic.

Design choice: kill-switches BLOCK new entries but never auto-close existing
positions. Auto-closing on kill is a risk-management *exit policy*, which is
strategy-specific and out of scope for this module. The live runner can
implement that on top of RiskManager.check_entry_allowed().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional


# =============================================================================
# PURE FUNCTIONS
# =============================================================================

def position_size_from_risk(
    equity: Decimal,
    risk_pct: Decimal,
    entry_price: Decimal,
    stop_price: Decimal,
) -> Decimal:
    """Compute position quantity such that loss-at-stop == risk_pct * equity.

    Args:
        equity: Current account equity in quote currency (e.g., USDT).
        risk_pct: Fraction of equity to risk per trade. 0.015 = 1.5%.
        entry_price: Entry fill price.
        stop_price: Stop-loss price.

    Returns:
        Quantity (base currency units, e.g., BTC) to trade.

    Raises:
        ValueError: if any input is non-positive or entry == stop.

    Example:
        equity=1000, risk_pct=0.015 (=15 USDT), entry=60000, stop=58800
        -> stop_distance = 1200
        -> qty = 15 / 1200 = 0.0125 BTC
        -> notional = 0.0125 * 60000 = 750 USDT
        -> if stop hits: -1200 * 0.0125 = -15 USDT (== 1.5% of 1000) ✓
    """
    if equity <= 0:
        raise ValueError(f"equity must be > 0, got {equity}")
    if risk_pct <= 0 or risk_pct >= 1:
        raise ValueError(f"risk_pct must be in (0, 1), got {risk_pct}")
    if entry_price <= 0 or stop_price <= 0:
        raise ValueError(f"prices must be > 0, got entry={entry_price}, stop={stop_price}")
    stop_distance = abs(entry_price - stop_price)
    if stop_distance == 0:
        raise ValueError("entry_price and stop_price are equal; no risk to size against")
    risk_amount = equity * risk_pct
    return risk_amount / stop_distance


# =============================================================================
# PORTFOLIO STATE
# =============================================================================

@dataclass
class PortfolioState:
    """Mutable state: equity, today's PnL, open positions per symbol.

    `today` is reset on the first realize_pnl() of a new UTC day, so the daily
    PnL tracker doesn't bleed across day boundaries.
    """
    initial_equity: Decimal
    current_equity: Decimal
    today: Optional[date] = None
    today_pnl: Decimal = Decimal("0")
    open_positions: dict[str, int] = field(default_factory=dict)

    @classmethod
    def fresh(cls, initial_equity: Decimal) -> "PortfolioState":
        if initial_equity <= 0:
            raise ValueError(f"initial_equity must be > 0, got {initial_equity}")
        return cls(initial_equity=initial_equity, current_equity=initial_equity)

    def realize_pnl(self, pnl: Decimal, when: datetime) -> None:
        """Apply realized PnL to equity and today's tracker."""
        if when.tzinfo is None:
            raise ValueError("when must be timezone-aware (UTC)")
        d = when.astimezone(timezone.utc).date()
        if self.today != d:
            self.today = d
            self.today_pnl = Decimal("0")
        self.today_pnl += pnl
        self.current_equity += pnl

    def open_position(self, symbol: str) -> None:
        self.open_positions[symbol] = self.open_positions.get(symbol, 0) + 1

    def close_position(self, symbol: str) -> None:
        n = self.open_positions.get(symbol, 0)
        if n <= 1:
            self.open_positions.pop(symbol, None)
        else:
            self.open_positions[symbol] = n - 1

    @property
    def total_open(self) -> int:
        return sum(self.open_positions.values())


# =============================================================================
# RISK MANAGER
# =============================================================================

@dataclass(frozen=True)
class RiskParams:
    risk_per_trade_pct: Decimal = Decimal("0.015")     # MASTERPLAN: 1.5%
    max_positions_per_symbol: int = 1                  # MASTERPLAN: 1
    max_total_positions: int = 2                       # MASTERPLAN: 2
    daily_loss_kill_pct: Decimal = Decimal("-0.10")    # MASTERPLAN: -10%
    aggregate_loss_kill_pct: Decimal = Decimal("-0.20")  # MASTERPLAN: -20%


@dataclass(frozen=True)
class EntryDecision:
    allowed: bool
    reason: str
    position_qty: Optional[Decimal] = None  # None if not allowed


class RiskManager:
    """Coordinates portfolio state + risk params to decide entries.

    Usage in a Strategy.on_bar():
        decision = rm.check_entry_allowed(symbol="BTCUSDT",
                                          entry_price=signal.entry_price,
                                          stop_price=signal.stop_price)
        if decision.allowed:
            place_order(qty=decision.position_qty)
            rm.state.open_position("BTCUSDT")
        # Later on close:
        rm.state.realize_pnl(pnl, when=exit_ts)
        rm.state.close_position("BTCUSDT")
    """

    def __init__(self, state: PortfolioState, params: RiskParams = RiskParams()):
        self.state = state
        self.params = params

    def check_entry_allowed(
        self, symbol: str, entry_price: Decimal, stop_price: Decimal
    ) -> EntryDecision:
        """Return EntryDecision with sizing if all kill-switches pass."""
        # Kill switches first (cheap)
        if self.state.current_equity <= 0:
            return EntryDecision(False, "account_busted")
        agg_pct = (self.state.current_equity - self.state.initial_equity) / self.state.initial_equity
        if agg_pct <= self.params.aggregate_loss_kill_pct:
            return EntryDecision(False, f"aggregate_kill (equity {agg_pct:.1%})")
        # Today's loss is fraction of *initial* equity (per MASTERPLAN), not current
        today_pct = self.state.today_pnl / self.state.initial_equity
        if today_pct <= self.params.daily_loss_kill_pct:
            return EntryDecision(False, f"daily_kill (today {today_pct:.1%})")
        # Position-count limits
        if self.state.open_positions.get(symbol, 0) >= self.params.max_positions_per_symbol:
            return EntryDecision(False, f"max_per_symbol ({symbol})")
        if self.state.total_open >= self.params.max_total_positions:
            return EntryDecision(False, "max_total_positions")
        # Size the position
        try:
            qty = position_size_from_risk(
                self.state.current_equity,
                self.params.risk_per_trade_pct,
                entry_price,
                stop_price,
            )
        except ValueError as e:
            return EntryDecision(False, f"sizing_error: {e}")
        return EntryDecision(True, "ok", position_qty=qty)

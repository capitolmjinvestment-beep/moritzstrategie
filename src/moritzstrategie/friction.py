"""Friction model: fees + funding + slippage.

Separate from the strategy and backtest engine so it can be A/B-tested.
The FrictionModel is composable: pick one fee schedule, one funding schedule,
one slippage model.

Why this matters (back-of-envelope):
  - Bitget USDT-Perp taker fee = 6 bps
  - Round-trip (entry + exit) = 12 bps per trade
  - At ~80 trades/year => 9.6%/year just from fees
  - Add funding (avg 0.01% per 8h hold) and 4h-bar slippage (2-5 bps each side)
  - Total friction can easily reach 15-20%/year

The strategy MUST clear this hurdle, not just produce positive gross returns.

Composition:
    friction = FrictionModel(
        fees=BitgetTakerFee(),         # or Maker, or Tiered
        funding=PeriodicFunding(...),  # per 8h
        slippage=ConstantSlippage(bps=5),  # or VolatilitySlippage (you implement)
    )

Usage in a backtest:
    entry_price_adjusted = friction.apply_entry_slippage(side, raw_price, atr)
    fee_cost = friction.fee_cost(notional)
    funding_cost = friction.funding_cost(notional, hours_held)
    net_pnl = gross_pnl - fee_cost - funding_cost
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .strategy import Side


# =============================================================================
# FEES
# =============================================================================

@dataclass(frozen=True)
class FeeSchedule(ABC):
    """Fee per side (entry or exit). Returns a fraction of notional."""

    @abstractmethod
    def rate(self, is_taker: bool) -> Decimal:
        """Return fee rate as fraction. 0.0006 = 6 bps = 0.06%."""

    def cost(self, notional: Decimal, is_taker: bool = True) -> Decimal:
        """Fee cost for one side of a trade."""
        return notional * self.rate(is_taker)


@dataclass(frozen=True)
class BitgetTakerFee(FeeSchedule):
    """Bitget USDT-Perpetual standard taker/maker fees (as of 2025-05).

    Assumes no VIP tier and no fee discounts. Update if you negotiate or hit a tier.
    Source: https://www.bitget.com/api-doc/common/account/Fee-Rates (verify before live).
    """
    taker_bps: Decimal = Decimal("6")   # 0.06%
    maker_bps: Decimal = Decimal("2")   # 0.02%

    def rate(self, is_taker: bool) -> Decimal:
        bps = self.taker_bps if is_taker else self.maker_bps
        return bps / Decimal("10000")


# =============================================================================
# FUNDING
# =============================================================================

@dataclass(frozen=True)
class FundingSchedule(ABC):
    """Perpetual-futures funding cost over a holding period."""

    @abstractmethod
    def cost(self, notional: Decimal, hours_held: Decimal, side: Side) -> Decimal:
        """Funding cost (positive = you pay, negative = you receive).

        For long positions: positive funding rate means longs pay shorts.
        For short positions: positive funding rate means shorts receive.
        """


@dataclass(frozen=True)
class PeriodicFunding(FundingSchedule):
    """Funding paid every 8h based on a static average rate.

    Real funding fluctuates (often -0.05% to +0.05% per 8h on majors).
    For backtest realism, use historical funding feeds. For sanity, use the average.

    Args:
        avg_rate_per_period: e.g. Decimal("0.0001") = 0.01% per 8h period.
            Positive value means longs typically pay shorts (most common in bull markets).
        period_hours: usually 8 for Bitget USDT-Perp.
    """
    avg_rate_per_period: Decimal = Decimal("0.0001")
    period_hours: Decimal = Decimal("8")

    def cost(self, notional: Decimal, hours_held: Decimal, side: Side) -> Decimal:
        """Approximate: count integer number of funding periods crossed.

        NOTE: This is a simplification. Real funding charges only fire at
        00:00, 08:00, 16:00 UTC (snapshot at that moment). A 4h trade entered
        at 04:00 and exited at 12:00 crosses one funding window (08:00).
        For sanity use we approximate as periods = hours_held / 8.
        """
        if notional <= 0 or hours_held <= 0:
            return Decimal("0")
        periods = hours_held / self.period_hours
        gross = notional * self.avg_rate_per_period * periods
        # Long pays positive rate; short receives positive rate (sign flip)
        return gross if side == Side.LONG else -gross


# =============================================================================
# SLIPPAGE
# =============================================================================

@dataclass(frozen=True)
class SlippageModel(ABC):
    """Slippage applied to a fill price.

    Returns the ADJUSTED price (worse than the raw signal price).
    For longs entering: adjusted > raw (you pay more).
    For longs exiting at stop: adjusted < raw (you sell lower).
    Symmetric for shorts.
    """

    @abstractmethod
    def apply(
        self,
        side: Side,
        is_entry: bool,
        raw_price: Decimal,
        atr: Optional[Decimal] = None,
    ) -> Decimal:
        """Return the slippage-adjusted fill price."""


@dataclass(frozen=True)
class ConstantSlippage(SlippageModel):
    """Constant slippage in basis points, applied symmetrically.

    Simplest possible model. Good for first-pass sanity.
    Real markets are NOT constant — slippage spikes during volatility events.
    """
    bps: Decimal = Decimal("5")

    def apply(
        self,
        side: Side,
        is_entry: bool,
        raw_price: Decimal,
        atr: Optional[Decimal] = None,
    ) -> Decimal:
        slip = raw_price * (self.bps / Decimal("10000"))
        # Worse-fill direction: long buys higher, long sells lower; short mirror
        if (side == Side.LONG and is_entry) or (side == Side.SHORT and not is_entry):
            return raw_price + slip
        return raw_price - slip


@dataclass(frozen=True)
class VolatilitySlippage(SlippageModel):
    """Slippage scales with ATR. Higher volatility => worse fills.

    This is the realistic model: market-order fills during volatile bars
    eat through deeper book layers. Empirically, slippage ~ α × (ATR / price).

    Args:
        alpha: scaling factor. Typical values 0.05 to 0.15.
            0.10 means slippage = 10% of (ATR/price) ratio applied as bps.
            e.g. ATR=100, price=10000 => ATR/price=0.01 => slippage = 0.001 = 10bps
        floor_bps: minimum slippage even in low-volatility regime.

    TODO (USER CONTRIBUTION):
        Implement `apply()`. Trade-offs to consider:
          - If ATR is None (early in series), what do you fall back to?
            Options: (a) raise ValueError, (b) use floor_bps only, (c) use a default.
          - Should you cap maximum slippage? A crash bar can have ATR > 5% of price,
            which would mean 50+ bps slippage. Realistic? Or too punitive?
          - Asymmetry: stop-orders typically slip WORSE than market entries
            (price gaps through stop, then bounces). Worth modeling?

        Recommended signature:
            slip = max(floor_bps, alpha × (atr / raw_price) × 10000)
            then apply same direction logic as ConstantSlippage.
    """
    alpha: Decimal = Decimal("0.10")
    floor_bps: Decimal = Decimal("3")
    cap_bps: Decimal = Decimal("30")

    def apply(
        self,
        side: Side,
        is_entry: bool,
        raw_price: Decimal,
        atr: Optional[Decimal] = None,
    ) -> Decimal:
        # Design decisions (per user: "mache du"):
        # 1. ATR=None -> fall back to floor_bps (backtest resilience > bug surfacing)
        # 2. Cap at cap_bps to avoid unrealistic 50+bps slippage on flash-crash bars
        # 3. No stop-asymmetry (belongs in live adapter, not sanity module)
        if atr is None or atr <= 0:
            slippage_bps = self.floor_bps
        else:
            scaled = self.alpha * (atr / raw_price) * Decimal("10000")
            slippage_bps = max(self.floor_bps, min(self.cap_bps, scaled))
        slip = raw_price * (slippage_bps / Decimal("10000"))
        if (side == Side.LONG and is_entry) or (side == Side.SHORT and not is_entry):
            return raw_price + slip
        return raw_price - slip


# =============================================================================
# COMPOSITE
# =============================================================================

@dataclass(frozen=True)
class FrictionModel:
    """Bundle of fee + funding + slippage models.

    The backtest engine consumes this opaquely; swap implementations to test
    sensitivity (e.g., "what if fees double?", "what if slippage triples?").
    """
    fees: FeeSchedule
    funding: FundingSchedule
    slippage: SlippageModel

    def apply_entry_slippage(
        self, side: Side, raw_price: Decimal, atr: Optional[Decimal] = None
    ) -> Decimal:
        return self.slippage.apply(side, is_entry=True, raw_price=raw_price, atr=atr)

    def apply_exit_slippage(
        self, side: Side, raw_price: Decimal, atr: Optional[Decimal] = None
    ) -> Decimal:
        return self.slippage.apply(side, is_entry=False, raw_price=raw_price, atr=atr)

    def fee_cost(self, notional: Decimal, is_taker: bool = True) -> Decimal:
        """Fee for one side (entry OR exit). Round-trip = call twice."""
        return self.fees.cost(notional, is_taker)

    def funding_cost(self, notional: Decimal, hours_held: Decimal, side: Side) -> Decimal:
        return self.funding.cost(notional, hours_held, side)

    def round_trip_friction_bps(
        self, notional: Decimal, hours_held: Decimal, side: Side
    ) -> Decimal:
        """Sanity helper: total friction as bps of notional for one round-trip trade.

        Does NOT include slippage (that's price-level, not cost-level).
        Use to quickly see fee+funding overhead.
        """
        fee = self.fees.cost(notional, is_taker=True) * Decimal("2")  # entry + exit
        funding = self.funding.cost(notional, hours_held, side)
        return (fee + funding) / notional * Decimal("10000")


def default_bitget_friction() -> FrictionModel:
    """Sensible default for Bitget USDT-Perp sanity backtests."""
    return FrictionModel(
        fees=BitgetTakerFee(),
        funding=PeriodicFunding(avg_rate_per_period=Decimal("0.0001")),
        slippage=ConstantSlippage(bps=Decimal("5")),
    )

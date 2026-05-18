"""Unit tests for the friction model.

The VolatilitySlippage tests are intentionally absent — those land
once the user implements VolatilitySlippage.apply().
"""

from decimal import Decimal

import pytest

from moritzstrategie.friction import (
    BitgetTakerFee,
    ConstantSlippage,
    FrictionModel,
    PeriodicFunding,
    VolatilitySlippage,
    default_bitget_friction,
)
from moritzstrategie.strategy import Side


# ---------- Fees ----------

def test_bitget_taker_fee_rate():
    f = BitgetTakerFee()
    assert f.rate(is_taker=True) == Decimal("0.0006")    # 6 bps
    assert f.rate(is_taker=False) == Decimal("0.0002")   # 2 bps


def test_fee_cost_per_side():
    f = BitgetTakerFee()
    # 10000 USDT notional at taker -> 6 USDT
    assert f.cost(Decimal("10000"), is_taker=True) == Decimal("6.0000")


def test_fee_zero_notional():
    f = BitgetTakerFee()
    assert f.cost(Decimal("0")) == Decimal("0")


# ---------- Funding ----------

def test_funding_long_pays_positive_rate():
    f = PeriodicFunding(avg_rate_per_period=Decimal("0.0001"))
    # 10000 notional, held 8h (= 1 period) at +0.01% -> 1 USDT cost
    cost = f.cost(Decimal("10000"), Decimal("8"), Side.LONG)
    assert cost == Decimal("1.0000")


def test_funding_short_receives_positive_rate():
    f = PeriodicFunding(avg_rate_per_period=Decimal("0.0001"))
    cost = f.cost(Decimal("10000"), Decimal("8"), Side.SHORT)
    assert cost == Decimal("-1.0000")  # negative = received


def test_funding_partial_period():
    f = PeriodicFunding(avg_rate_per_period=Decimal("0.0001"))
    # 4h hold = half period
    cost = f.cost(Decimal("10000"), Decimal("4"), Side.LONG)
    assert cost == Decimal("0.5000")


def test_funding_zero_hours():
    f = PeriodicFunding()
    assert f.cost(Decimal("10000"), Decimal("0"), Side.LONG) == Decimal("0")


def test_funding_zero_notional():
    f = PeriodicFunding()
    assert f.cost(Decimal("0"), Decimal("8"), Side.LONG) == Decimal("0")


# ---------- Slippage ----------

def test_constant_slippage_long_entry_pays_more():
    s = ConstantSlippage(bps=Decimal("5"))
    # Long entry: raw 10000, +5bps = 10005
    assert s.apply(Side.LONG, is_entry=True, raw_price=Decimal("10000")) == Decimal("10005.0000")


def test_constant_slippage_long_exit_gets_less():
    s = ConstantSlippage(bps=Decimal("5"))
    assert s.apply(Side.LONG, is_entry=False, raw_price=Decimal("10000")) == Decimal("9995.0000")


def test_constant_slippage_short_entry_gets_less():
    s = ConstantSlippage(bps=Decimal("5"))
    # Short entry: sell at slightly lower price -> raw - slip
    assert s.apply(Side.SHORT, is_entry=True, raw_price=Decimal("10000")) == Decimal("9995.0000")


def test_constant_slippage_short_exit_pays_more():
    s = ConstantSlippage(bps=Decimal("5"))
    assert s.apply(Side.SHORT, is_entry=False, raw_price=Decimal("10000")) == Decimal("10005.0000")


def test_volatility_slippage_long_entry_with_atr():
    """ATR=100, price=10000 -> atr/price=0.01 -> 100bps -> *0.10 alpha -> 10bps."""
    s = VolatilitySlippage(alpha=Decimal("0.10"))
    out = s.apply(Side.LONG, True, Decimal("10000"), atr=Decimal("100"))
    # 10bps of 10000 = 10
    assert out == Decimal("10010.0000")


def test_volatility_slippage_falls_back_to_floor_when_atr_none():
    s = VolatilitySlippage(floor_bps=Decimal("3"))
    out = s.apply(Side.LONG, True, Decimal("10000"), atr=None)
    # 3bps of 10000 = 3
    assert out == Decimal("10003.0000")


def test_volatility_slippage_caps_at_cap_bps():
    """ATR huge -> would compute 50bps -> capped at 30bps default."""
    s = VolatilitySlippage(alpha=Decimal("0.10"), cap_bps=Decimal("30"))
    # ATR/price = 0.05 -> 500bps -> *0.10 = 50bps -> capped to 30
    out = s.apply(Side.LONG, True, Decimal("10000"), atr=Decimal("500"))
    # 30bps of 10000 = 30
    assert out == Decimal("10030.0000")


def test_volatility_slippage_enforces_floor():
    """Low ATR would compute below floor -> floor wins."""
    s = VolatilitySlippage(alpha=Decimal("0.10"), floor_bps=Decimal("3"))
    # ATR/price = 0.0001 -> 1bp -> *0.10 = 0.1bp -> floored to 3
    out = s.apply(Side.LONG, True, Decimal("10000"), atr=Decimal("1"))
    assert out == Decimal("10003.0000")


def test_volatility_slippage_direction_short_entry():
    s = VolatilitySlippage(alpha=Decimal("0.10"))
    out = s.apply(Side.SHORT, True, Decimal("10000"), atr=Decimal("100"))
    # Short entry sells lower
    assert out == Decimal("9990.0000")


def test_volatility_slippage_direction_long_exit():
    s = VolatilitySlippage(alpha=Decimal("0.10"))
    out = s.apply(Side.LONG, False, Decimal("10000"), atr=Decimal("100"))
    # Long exit sells lower
    assert out == Decimal("9990.0000")


# ---------- Composite ----------

def test_friction_model_round_trip_bps():
    f = default_bitget_friction()
    # 10000 notional, 24h hold (=3 periods at 0.01% each), long
    bps = f.round_trip_friction_bps(Decimal("10000"), Decimal("24"), Side.LONG)
    # 2 × 6bps fee = 12bps + 3 × 1bp funding = 15bps total
    assert bps == Decimal("15")


def test_friction_model_round_trip_short_funding_credit():
    f = default_bitget_friction()
    # Short in positive-funding regime: receives funding, lower total cost
    bps = f.round_trip_friction_bps(Decimal("10000"), Decimal("24"), Side.SHORT)
    # 12bps fee - 3bps funding-received = 9bps total
    assert bps == Decimal("9")


def test_friction_model_entry_exit_slippage():
    f = default_bitget_friction()
    entry = f.apply_entry_slippage(Side.LONG, Decimal("100"))
    exit_ = f.apply_exit_slippage(Side.LONG, Decimal("105"))
    assert entry > Decimal("100")
    assert exit_ < Decimal("105")

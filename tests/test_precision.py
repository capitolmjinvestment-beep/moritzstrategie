"""Tests for tick-size quantization."""

from decimal import Decimal

import pytest

from moritzstrategie.precision import (
    BITGET_TICK_SIZES,
    quantize_camarilla,
    quantize_price,
    tick_for,
)


# ---------- quantize_price ----------

def test_quantize_btc_tick():
    assert quantize_price(Decimal("60123.456789"), Decimal("0.1")) == Decimal("60123.5")


def test_quantize_rounds_half_up():
    # 60000.05 with tick 0.1 -> exactly halfway, HALF_UP rounds to 0.1
    assert quantize_price(Decimal("60000.05"), Decimal("0.1")) == Decimal("60000.1")
    # 60000.04 -> rounds down
    assert quantize_price(Decimal("60000.04"), Decimal("0.1")) == Decimal("60000.0")


def test_quantize_eth_tick():
    assert quantize_price(Decimal("3000.12345"), Decimal("0.01")) == Decimal("3000.12")


def test_quantize_already_aligned_returns_same():
    assert quantize_price(Decimal("60000.0"), Decimal("0.1")) == Decimal("60000.0")


def test_quantize_camarilla_p_non_terminating():
    """The exact issue from REVIEW.md H1: P = (H+L+C)/3 doesn't terminate."""
    p_raw = (Decimal("60100") + Decimal("60000") + Decimal("60050")) / Decimal("3")
    # 180150/3 = 60050 exactly, no problem. Try a case that DOES diverge:
    p_raw = (Decimal("60100") + Decimal("59999") + Decimal("60001")) / Decimal("3")
    # = 60033.333... (non-terminating)
    quantized = quantize_price(p_raw, Decimal("0.1"))
    assert quantized == Decimal("60033.3")


def test_quantize_rejects_zero_tick():
    with pytest.raises(ValueError, match="tick must be > 0"):
        quantize_price(Decimal("100"), Decimal("0"))


def test_quantize_rejects_negative_price():
    with pytest.raises(ValueError, match="price must be >= 0"):
        quantize_price(Decimal("-100"), Decimal("0.1"))


def test_quantize_zero_price_ok():
    assert quantize_price(Decimal("0"), Decimal("0.1")) == Decimal("0.0")


# ---------- quantize_camarilla ----------

def test_quantize_camarilla_all_levels():
    levels = {
        "H3": Decimal("60123.456"),
        "L3": Decimal("59876.543"),
        "P":  Decimal("60000.123"),
    }
    out = quantize_camarilla(levels, Decimal("0.1"))
    assert out["H3"] == Decimal("60123.5")
    assert out["L3"] == Decimal("59876.5")
    assert out["P"] == Decimal("60000.1")


# ---------- tick_for ----------

def test_tick_for_known_symbol():
    assert tick_for("BTCUSDT") == Decimal("0.1")
    assert tick_for("ETHUSDT") == Decimal("0.01")


def test_tick_for_unknown_raises():
    with pytest.raises(KeyError, match="Unknown symbol"):
        tick_for("UNKNOWNUSDT")

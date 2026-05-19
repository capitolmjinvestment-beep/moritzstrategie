"""Tests for Fibonacci retracement / extension levels."""

from decimal import Decimal

import pytest

from moritzstrategie.fibonacci import (
    EXTENSION_RATIOS,
    RETRACEMENT_RATIOS,
    FibonacciLevels,
    SwingDirection,
    compute_fibonacci,
)


# ---------- compute_fibonacci ----------

def test_up_swing_retracement_endpoints():
    """For UP swing: 0.0 = swing_high, 1.0 = swing_low."""
    fib = compute_fibonacci(Decimal("100"), Decimal("200"), SwingDirection.UP)
    assert fib.retracement(Decimal("0.000")) == Decimal("200")
    assert fib.retracement(Decimal("1.000")) == Decimal("100")


def test_up_swing_618_retracement():
    """0.618 retracement of a 100-point UP swing from 100 -> 200:
    200 - 0.618 * 100 = 138.2"""
    fib = compute_fibonacci(Decimal("100"), Decimal("200"), SwingDirection.UP)
    assert fib.retracement(Decimal("0.618")) == Decimal("138.200")


def test_up_swing_382_retracement():
    fib = compute_fibonacci(Decimal("100"), Decimal("200"), SwingDirection.UP)
    # 200 - 0.382 * 100 = 161.8
    assert fib.retracement(Decimal("0.382")) == Decimal("161.800")


def test_down_swing_retracement_endpoints():
    """For DOWN swing: 0.0 = swing_low, 1.0 = swing_high."""
    fib = compute_fibonacci(Decimal("100"), Decimal("200"), SwingDirection.DOWN)
    assert fib.retracement(Decimal("0.000")) == Decimal("100")
    assert fib.retracement(Decimal("1.000")) == Decimal("200")


def test_down_swing_618_retracement():
    """0.618 retracement of a DOWN swing from 200 -> 100: bounce to 100 + 0.618*100 = 161.8"""
    fib = compute_fibonacci(Decimal("100"), Decimal("200"), SwingDirection.DOWN)
    assert fib.retracement(Decimal("0.618")) == Decimal("161.800")


# ---------- extensions ----------

def test_up_swing_extension_1272():
    """1.272 extension of UP swing 100->200: 200 + 0.272*100 = 227.2"""
    fib = compute_fibonacci(Decimal("100"), Decimal("200"), SwingDirection.UP)
    assert fib.extension(Decimal("1.272")) == Decimal("227.200")


def test_up_swing_extension_1618():
    """Golden extension: 200 + 0.618*100 = 261.8"""
    fib = compute_fibonacci(Decimal("100"), Decimal("200"), SwingDirection.UP)
    assert fib.extension(Decimal("1.618")) == Decimal("261.800")


def test_down_swing_extension_1618():
    """DOWN swing 200->100, 1.618 extension: 100 - 0.618*100 = 38.2"""
    fib = compute_fibonacci(Decimal("100"), Decimal("200"), SwingDirection.DOWN)
    assert fib.extension(Decimal("1.618")) == Decimal("38.200")


# ---------- API ergonomics ----------

def test_all_canonical_levels_in_dict():
    fib = compute_fibonacci(Decimal("100"), Decimal("200"), SwingDirection.UP)
    for r in RETRACEMENT_RATIOS:
        assert r in fib.retracements
    for e in EXTENSION_RATIOS:
        assert e in fib.extensions


def test_interpolation_for_non_canonical_ratio():
    """Custom ratio (e.g. 0.5) — works even if not pre-cached."""
    fib = compute_fibonacci(Decimal("100"), Decimal("200"), SwingDirection.UP)
    # 0.5 IS in canonical set (RETRACEMENT_RATIOS contains 0.500)
    assert fib.retracement(Decimal("0.5")) == Decimal("150.000")
    # 0.25 is not
    assert fib.retracement(Decimal("0.25")) == Decimal("175.00")


def test_range_property():
    fib = compute_fibonacci(Decimal("100"), Decimal("200"), SwingDirection.UP)
    assert fib.range == Decimal("100")


# ---------- Validation ----------

def test_rejects_zero_price():
    with pytest.raises(ValueError, match="prices must be > 0"):
        compute_fibonacci(Decimal("0"), Decimal("100"), SwingDirection.UP)


def test_rejects_high_less_than_low():
    with pytest.raises(ValueError, match="swing_high"):
        compute_fibonacci(Decimal("200"), Decimal("100"), SwingDirection.UP)


def test_rejects_equal_prices():
    with pytest.raises(ValueError, match="swing_high"):
        compute_fibonacci(Decimal("100"), Decimal("100"), SwingDirection.UP)

"""Unit tests for RSI and ATR (Wilder smoothing).

Reference values taken from the canonical Wilder (1978) RSI table used by
ta-lib and TradingView. If you change the formula, these tests will catch it.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from moritzstrategie.atr import compute_atr
from moritzstrategie.rsi import compute_rsi
from moritzstrategie.types import Bar


UTC = timezone.utc


def _bars_from_closes(closes: list[str], hl_spread: str = "1.0") -> list[Bar]:
    """Build minimal bars where high = close + spread/2, low = close - spread/2."""
    spread = Decimal(hl_spread) / Decimal("2")
    out = []
    for i, c in enumerate(closes):
        cd = Decimal(c)
        out.append(
            Bar(
                ts=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=4 * i),
                open=cd, high=cd + spread, low=cd - spread,
                close=cd, volume=Decimal("1"),
            )
        )
    return out


# ---------- RSI ----------

# Wilder's classic example dataset (Cutler-adjusted)
# Source: Wilder, J. Welles. "New Concepts in Technical Trading Systems", 1978
_WILDER_CLOSES = [
    "44.34", "44.09", "44.15", "43.61", "44.33", "44.83", "45.10",
    "45.42", "45.84", "46.08", "45.89", "46.03", "45.61", "46.28",
    "46.28", "46.00", "46.03", "46.41", "46.22", "45.64", "46.21",
    "46.25", "45.71", "46.45", "45.78", "45.35", "44.03", "44.18",
    "44.22", "44.57", "43.42", "42.66", "43.13",
]


def test_rsi_first_period_values_are_none():
    closes = [Decimal(c) for c in _WILDER_CLOSES]
    rsi = compute_rsi(closes, period=14)
    assert len(rsi) == len(closes)
    for i in range(14):
        assert rsi[i] is None, f"rsi[{i}] should be None, got {rsi[i]}"
    assert rsi[14] is not None


def test_rsi_known_value_against_reference():
    """RSI at idx=14 of Wilder's dataset should be ~70.46 (TradingView-confirmed).

    Per code review H3: tightened from +/-1.0 to +/-0.1 to catch off-by-one seed bugs.
    """
    closes = [Decimal(c) for c in _WILDER_CLOSES]
    rsi = compute_rsi(closes, period=14)
    val = rsi[14]
    assert val is not None
    assert Decimal("70.4") < val < Decimal("70.6"), f"expected ~70.46, got {val}"


def test_rsi_in_range_zero_to_hundred():
    closes = [Decimal(c) for c in _WILDER_CLOSES]
    for val in compute_rsi(closes, period=14):
        if val is not None:
            assert Decimal("0") <= val <= Decimal("100")


def test_rsi_all_up_moves_returns_100():
    """If price strictly rises, avg_loss = 0 -> RSI = 100."""
    closes = [Decimal(str(100 + i)) for i in range(20)]
    rsi = compute_rsi(closes, period=14)
    for v in rsi[14:]:
        assert v == Decimal("100")


def test_rsi_all_down_moves_returns_0():
    closes = [Decimal(str(100 - i)) for i in range(20)]
    rsi = compute_rsi(closes, period=14)
    for v in rsi[14:]:
        assert v == Decimal("0")


def test_rsi_flat_prices_returns_neutral():
    """All prices equal -> avg_gain = avg_loss = 0 -> we return 50 (neutral)."""
    closes = [Decimal("100")] * 20
    rsi = compute_rsi(closes, period=14)
    for v in rsi[14:]:
        assert v == Decimal("50")


def test_rsi_returns_decimal_only():
    closes = [Decimal(c) for c in _WILDER_CLOSES]
    for v in compute_rsi(closes, period=14):
        assert v is None or isinstance(v, Decimal)


def test_rsi_no_lookahead():
    """RSI at index i must be identical whether we pass closes[:i+1] or closes[:N].

    This is THE look-ahead test: the value at i may only depend on data <= i.
    """
    closes = [Decimal(c) for c in _WILDER_CLOSES]
    full = compute_rsi(closes, period=14)
    for i in range(15, len(closes)):
        truncated = compute_rsi(closes[:i + 1], period=14)
        assert truncated[i] == full[i], f"lookahead at i={i}: {truncated[i]} vs {full[i]}"


def test_rsi_insufficient_data():
    closes = [Decimal("100")] * 10
    rsi = compute_rsi(closes, period=14)
    assert all(v is None for v in rsi)


def test_rsi_invalid_period():
    with pytest.raises(ValueError):
        compute_rsi([Decimal("100")] * 20, period=0)


# ---------- ATR ----------

def test_atr_first_period_values_are_none():
    bars = _bars_from_closes(_WILDER_CLOSES, hl_spread="0.5")
    atr = compute_atr(bars, period=14)
    assert len(atr) == len(bars)
    for i in range(14):
        assert atr[i] is None
    assert atr[14] is not None


def test_atr_positive_and_decimal():
    bars = _bars_from_closes(_WILDER_CLOSES, hl_spread="1.0")
    for v in compute_atr(bars, period=14):
        if v is not None:
            assert isinstance(v, Decimal)
            assert v > 0


def test_atr_captures_gap_up():
    """Gap up: TR should be |high - prev_close|, not just (high - low)."""
    # 5 bars at 100, then a gap up to 110 with tiny intra-bar range
    closes = ["100"] * 5 + ["110"]
    bars = _bars_from_closes(closes, hl_spread="0.1")
    # Bar 5: high = 110.05, low = 109.95, prev_close = 100
    # TR = max(0.1, |110.05 - 100| = 10.05, |109.95 - 100| = 9.95) = 10.05
    atr = compute_atr(bars, period=2)
    # period=2 -> seed at idx=2, last value reflects the gap
    assert atr[5] is not None
    # ATR at idx=5 must reflect the gap (some smoothing) - significantly > spread
    assert atr[5] > Decimal("1.0"), f"ATR should reflect gap, got {atr[5]}"


def test_atr_no_lookahead():
    bars = _bars_from_closes(_WILDER_CLOSES, hl_spread="0.8")
    full = compute_atr(bars, period=14)
    for i in range(15, len(bars)):
        truncated = compute_atr(bars[:i + 1], period=14)
        assert truncated[i] == full[i], f"lookahead at i={i}"


def test_atr_insufficient_data():
    bars = _bars_from_closes(["100"] * 10)
    assert all(v is None for v in compute_atr(bars, period=14))


def test_atr_invalid_period():
    bars = _bars_from_closes(["100"] * 20)
    with pytest.raises(ValueError):
        compute_atr(bars, period=0)

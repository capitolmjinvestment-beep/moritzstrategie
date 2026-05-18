"""Unit tests for evaluate_entry().

Strategy: each test isolates ONE entry condition by making the others trivially true,
then violates the target condition. Lets us prove "this exact rule blocks this exact case".
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from moritzstrategie.strategy import EntryParams, Side, evaluate_entry
from moritzstrategie.types import Bar


UTC = timezone.utc


def _bar(idx: int, o, h, l, c, v="1") -> Bar:
    return Bar(
        ts=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=4 * idx),
        open=Decimal(str(o)), high=Decimal(str(h)),
        low=Decimal(str(l)), close=Decimal(str(c)),
        volume=Decimal(v),
    )


def _build_long_setup() -> tuple[list[Bar], dict[str, Decimal]]:
    """Construct a canonical long-setup window that should fire.

    - L3 = 95, H3 = 110, P = 100
    - Big down-move into L3 (drives RSI < 30)
    - Double-bottom at idx ~16 and idx ~22, both <= 95
    - Final bar (idx 25) closes above neckline and RSI recovers > 30
    """
    bars: list[Bar] = []

    # Pre-history: gentle uptrend (RSI > 30 baseline)
    price = 110
    for i in range(8):
        bars.append(_bar(i, price, price + 1, price - 1, price + 0.5))
        price += 0.5

    # Sharp drop to drive RSI < 30
    for i in range(8, 16):
        last = float(bars[-1].close)
        new_close = last - 2.0
        bars.append(_bar(i, last, last + 0.1, new_close - 0.1, new_close))

    # Idx 16: first low at ~95
    last = float(bars[-1].close)
    bars.append(_bar(16, last, last + 0.1, 94.5, 95.0))

    # Bounce up so a neckline can form
    for i in range(17, 22):
        last = float(bars[-1].close)
        new_close = last + 1.0
        bars.append(_bar(i, last, last + 1.5, last, new_close))

    # Idx 22: second low at ~95
    last = float(bars[-1].close)
    bars.append(_bar(22, last, last + 0.1, 94.5, 95.0))

    # Idx 23-24: recovery bars
    for i in range(23, 25):
        last = float(bars[-1].close)
        new_close = last + 0.5
        bars.append(_bar(i, last, last + 1, last - 0.1, new_close))

    # Idx 25: trigger bar - close ABOVE neckline (~102)
    last = float(bars[-1].close)
    bars.append(_bar(25, last, 105, last - 0.1, 104))  # close 104 > any neckline in the window

    cam = {"L3": Decimal("95"), "H3": Decimal("110"), "P": Decimal("100")}
    return bars, cam


# ---------- Sanity: the canonical setup fires ----------

def test_canonical_long_setup_fires():
    bars, cam = _build_long_setup()
    sig = evaluate_entry(bars, current_idx=len(bars) - 1, camarilla=cam)
    assert sig is not None, "canonical long setup must fire"
    assert sig.side == Side.LONG
    assert sig.entry_price == bars[-1].close
    assert sig.tp1_price == cam["P"]
    assert sig.tp2_price == cam["H3"]
    # Stop is min(95, 95) - 0.5*ATR -> below 95
    assert sig.stop_price < Decimal("95")


# ---------- Block on each individual condition ----------

def test_blocks_when_no_pivot_touch():
    bars, cam = _build_long_setup()
    # Move L3 way below market so nothing ever touched it
    cam = {**cam, "L3": Decimal("50")}
    sig = evaluate_entry(bars, current_idx=len(bars) - 1, camarilla=cam)
    assert sig is None


def test_blocks_when_rsi_never_oversold():
    bars, cam = _build_long_setup()
    # Raise the oversold threshold to 100 -> impossible to ever trigger
    params = EntryParams(rsi_oversold=Decimal("0"))  # RSI never below 0
    sig = evaluate_entry(bars, current_idx=len(bars) - 1, camarilla=cam, params=params)
    assert sig is None


def test_blocks_when_no_double_bottom():
    bars, cam = _build_long_setup()
    # Tighten max_pct_diff so the two ~95 lows cannot pair (they differ by 0)
    # Actually they are equal -> tighten to 0 -> still equal passes (diff=0 <= 0)
    # Better: tighten min_separation huge
    params = EntryParams(pattern_min_separation=50)
    sig = evaluate_entry(bars, current_idx=len(bars) - 1, camarilla=cam, params=params)
    assert sig is None


def test_blocks_when_close_below_neckline():
    """If the trigger bar closes BELOW the neckline, no signal."""
    bars, cam = _build_long_setup()
    # Replace last bar with one that closes BELOW any plausible neckline
    bars[-1] = _bar(25, 98, 99, 94, 94.5)
    sig = evaluate_entry(bars, current_idx=len(bars) - 1, camarilla=cam)
    assert sig is None


# ---------- Look-ahead test ----------

def test_evaluate_entry_no_lookahead():
    """Signal at idx=i must not depend on bars beyond i.

    We run evaluate_entry on bars[:i+1] (truncated) vs bars (full); the result at i
    must be identical regardless of bars after i.
    """
    bars, cam = _build_long_setup()
    target = len(bars) - 1

    # Append "future" bars that would change things if seen
    future = [_bar(target + 1 + k, 50, 51, 30, 35) for k in range(5)]
    extended = bars + future

    sig_truncated = evaluate_entry(bars, current_idx=target, camarilla=cam)
    sig_extended = evaluate_entry(extended, current_idx=target, camarilla=cam)

    assert sig_truncated == sig_extended


# ---------- Insufficient history ----------

def test_returns_none_for_short_history():
    bars = [_bar(i, 100, 101, 99, 100) for i in range(5)]
    cam = {"L3": Decimal("95"), "H3": Decimal("105"), "P": Decimal("100")}
    assert evaluate_entry(bars, current_idx=4, camarilla=cam) is None


def test_returns_none_for_out_of_range_idx():
    bars = [_bar(i, 100, 101, 99, 100) for i in range(20)]
    cam = {"L3": Decimal("95"), "H3": Decimal("105"), "P": Decimal("100")}
    assert evaluate_entry(bars, current_idx=-1, camarilla=cam) is None
    assert evaluate_entry(bars, current_idx=999, camarilla=cam) is None


def test_returns_none_when_camarilla_levels_missing():
    bars, _ = _build_long_setup()
    sig = evaluate_entry(bars, current_idx=len(bars) - 1, camarilla={})
    assert sig is None


# ---------- Stop/TP placement sanity ----------

def test_long_stop_below_entry_tp_above():
    bars, cam = _build_long_setup()
    sig = evaluate_entry(bars, current_idx=len(bars) - 1, camarilla=cam)
    assert sig is not None
    assert sig.stop_price < sig.entry_price, "long stop must be below entry"
    assert sig.tp1_price < sig.tp2_price or sig.tp1_price > sig.tp2_price  # they differ
    # For long: TP1 = P, TP2 = H3, P < H3
    assert sig.tp1_price < sig.tp2_price

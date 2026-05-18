"""Unit tests for Double-Top/Bottom pattern detector.

Pivot definition: k-bar window (k=2) with strict < / >.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from moritzstrategie.patterns import (
    _is_local_high,
    _is_local_low,
    detect_double_bottom,
    detect_double_top,
)
from moritzstrategie.types import Bar, Pattern


UTC = timezone.utc


def _make_bars(lows_highs: list[tuple[str, str]], start_ts: datetime = datetime(2025, 1, 1, tzinfo=UTC)) -> list[Bar]:
    """Build a sequence of synthetic 4h bars from (low, high) tuples.

    Open and close are placed mid-range to satisfy Bar invariants.
    """
    bars = []
    for i, (lo, hi) in enumerate(lows_highs):
        lo_d, hi_d = Decimal(lo), Decimal(hi)
        mid = (lo_d + hi_d) / Decimal("2")
        bars.append(
            Bar(
                ts=start_ts + timedelta(hours=4 * i),
                open=mid, high=hi_d, low=lo_d, close=mid,
                volume=Decimal("1"),
            )
        )
    return bars


# ---------- _is_local_low / _is_local_high ----------

def test_local_low_strict_minimum_in_window():
    # idx=4 is the strict min over [2,6]. Lows: 102,101,100,99,95,99,100,101,102
    bars = _make_bars([
        ("102", "110"), ("101", "110"), ("100", "110"),
        ("99",  "110"),
        ("95",  "110"),                              # <- idx=4, the pivot
        ("99",  "110"), ("100", "110"),
        ("101", "110"), ("102", "110"),
    ])
    assert _is_local_low(bars, 4) is True
    assert _is_local_low(bars, 3) is False  # 95 to the right is lower
    assert _is_local_low(bars, 5) is False  # 95 to the left is lower


def test_local_low_rejects_edge_indices():
    bars = _make_bars([("100", "110")] * 5)
    # k=2: indices 0, 1, len-2, len-1 cannot be pivots
    assert _is_local_low(bars, 0) is False
    assert _is_local_low(bars, 1) is False
    assert _is_local_low(bars, 3) is False
    assert _is_local_low(bars, 4) is False


def test_local_low_rejects_equal_neighbors():
    """Strict `<` means equal lows do NOT count as pivots (round-number guard)."""
    bars = _make_bars([
        ("100", "110"), ("100", "110"), ("100", "110"),  # tie at idx=2
        ("100", "110"), ("100", "110"),
    ])
    assert _is_local_low(bars, 2) is False


def test_local_high_strict_maximum_in_window():
    bars = _make_bars([
        ("90", "100"), ("90", "101"), ("90", "102"),
        ("90", "103"),
        ("90", "108"),                              # <- pivot high at idx=4
        ("90", "103"), ("90", "102"),
        ("90", "101"), ("90", "100"),
    ])
    assert _is_local_high(bars, 4) is True
    assert _is_local_high(bars, 3) is False
    assert _is_local_high(bars, 5) is False


# ---------- detect_double_bottom ----------

def test_double_bottom_happy_path():
    # Two lows: idx=2 at 95, idx=7 at 95.5 (within 1.5%), separated by 5 bars,
    # both below L3=96. Neckline is the high between them.
    bars = _make_bars([
        ("100", "105"),    # 0
        ("99",  "104"),    # 1
        ("95",  "100"),    # 2  <- low #1
        ("96",  "101"),    # 3
        ("97",  "103"),    # 4  <- highest between
        ("96",  "101"),    # 5
        ("96",  "100"),    # 6
        ("95.5","99"),     # 7  <- low #2
        ("96",  "100"),    # 8
        ("97",  "102"),    # 9
    ])
    res = detect_double_bottom(bars, level_threshold=Decimal("96"))
    assert res.pattern == Pattern.DOUBLE_BOTTOM
    assert res.idx_1 == 2
    assert res.idx_2 == 7
    assert res.extreme_1 == Decimal("95")
    assert res.extreme_2 == Decimal("95.5")
    assert res.neckline == Decimal("103")  # highest high between idx 3..6


def test_double_bottom_rejected_when_lows_too_far_apart_in_pct():
    bars = _make_bars([
        ("100", "105"), ("99", "104"),
        ("90",  "100"),                # low at 90
        ("96",  "101"), ("97", "103"), ("96", "101"), ("96", "100"),
        ("95",  "99"),                 # low at 95 -> diff > 1.5%
        ("96",  "100"), ("97", "102"),
    ])
    res = detect_double_bottom(bars, level_threshold=Decimal("96"))
    assert res.pattern == Pattern.NONE


def test_double_bottom_rejected_when_too_close_in_time():
    bars = _make_bars([
        ("100", "105"), ("99", "104"),
        ("95",  "100"),                # idx 2 low
        ("96",  "103"),                # idx 3 (only 1 bar separation)
        ("95.2","99"),                 # idx 4 low - sep = 2 < 3
        ("96",  "101"), ("97", "102"),
    ])
    res = detect_double_bottom(bars, level_threshold=Decimal("96"))
    assert res.pattern == Pattern.NONE


def test_double_bottom_rejected_when_lows_above_threshold():
    bars = _make_bars([
        ("100", "105"), ("99", "104"),
        ("97",  "100"),                # low at 97 - ABOVE threshold 96
        ("98",  "101"), ("99", "103"), ("98", "101"), ("98", "100"),
        ("97",  "99"),
        ("98",  "100"), ("99", "102"),
    ])
    res = detect_double_bottom(bars, level_threshold=Decimal("96"))
    assert res.pattern == Pattern.NONE


def test_double_bottom_picks_most_recent_when_multiple_candidates():
    """If three valid lows form two valid pairs, the pair with the LATER second-low wins."""
    bars = _make_bars([
        ("100", "105"), ("99", "104"),
        ("95",  "100"),                # idx 2 low A
        ("96",  "101"), ("97", "103"), ("96", "101"), ("96", "100"),
        ("95",  "99"),                 # idx 7 low B
        ("96",  "100"), ("97", "102"), ("96", "100"), ("96", "100"),
        ("95",  "99"),                 # idx 12 low C  <- newest
        ("96",  "100"), ("97", "102"),
    ])
    res = detect_double_bottom(bars, level_threshold=Decimal("96"))
    assert res.pattern == Pattern.DOUBLE_BOTTOM
    assert res.idx_2 == 12  # most recent


def test_double_bottom_empty_or_too_short_input():
    assert detect_double_bottom([], level_threshold=Decimal("100")).pattern == Pattern.NONE
    short = _make_bars([("95", "100"), ("95", "100")])
    assert detect_double_bottom(short, level_threshold=Decimal("100")).pattern == Pattern.NONE


# ---------- detect_double_top (mirror) ----------

def test_double_top_happy_path():
    # Two highs at H3=104: idx=2 at 105, idx=7 at 104.5
    bars = _make_bars([
        ("99",  "100"),   # 0
        ("100", "101"),   # 1
        ("100", "105"),   # 2  <- high #1
        ("99",  "104"),   # 3
        ("97",  "100"),   # 4  <- lowest between
        ("99",  "104"),   # 5
        ("100", "104"),   # 6
        ("100", "104.5"), # 7  <- high #2
        ("99",  "104"),   # 8
        ("98",  "103"),   # 9
    ])
    res = detect_double_top(bars, level_threshold=Decimal("104"))
    assert res.pattern == Pattern.DOUBLE_TOP
    assert res.idx_1 == 2
    assert res.idx_2 == 7
    assert res.extreme_1 == Decimal("105")
    assert res.extreme_2 == Decimal("104.5")
    assert res.neckline == Decimal("97")  # lowest low between


def test_pivot_requires_2_bars_forward_confirmation():
    """C3 from code review: with k=2, a pivot at idx requires 2 confirming bars after it.

    Pins down the implicit behavior: the latest possible pivot in a window of N bars
    is at idx N-3 (needs bars N-2 and N-1 as confirmation).
    """
    bars = _make_bars([
        ("100", "110"), ("99", "110"), ("98", "110"),
        ("95", "110"),   # idx 3 - low here
        ("99", "110"),   # idx 4 - 1 confirming bar
    ])
    # Window of 5: idx 3 has only 1 confirming bar -> not a pivot
    assert _is_local_low(bars, 3) is False
    # Extend with one more bar
    bars_extended = bars + _make_bars([("99", "110")])  # idx 5
    # Now idx 3 has 2 confirming bars (idx 4, idx 5) -> pivot
    assert _is_local_low(bars_extended, 3) is True


def test_double_bottom_minimum_separation_exactly_equals_param():
    """H5 from code review: separation == min_separation should pass, not be excluded."""
    bars = _make_bars([
        ("100", "105"), ("99", "104"),
        ("95",  "100"),   # idx 2 low #1
        ("96",  "101"),   # idx 3
        ("96",  "101"),   # idx 4
        ("95",  "100"),   # idx 5 low #2 - exactly min_separation=3 from idx 2
        ("96",  "100"),   # idx 6
        ("97",  "102"),   # idx 7
        ("98",  "103"),   # idx 8
    ])
    res = detect_double_bottom(bars, level_threshold=Decimal("96"), min_separation=3)
    # idx 2 and idx 5 are 3 apart -> sep >= min_separation should hold
    # Note: idx 5 may not qualify as a pivot if k=2 requires confirming bars after.
    # This test documents the actual behavior, which may need both 5 sep AND k=2 to align.
    # The implicit pivot k=2 means idx 5 needs bars at idx 6 AND idx 7 to be strictly higher.
    # Here both are higher (96, 97 vs 95). So idx 5 is a pivot.
    assert res.pattern == Pattern.DOUBLE_BOTTOM
    assert res.idx_1 == 2
    assert res.idx_2 == 5


def test_pivot_k_parameter_changes_pattern_count():
    """k=1 finds patterns that k=2 misses (looser pivot definition = more patterns).

    Built so middle lows are local mins over k=1 (1 bar each side) but boundary
    bars don't have k=2 confirmation (need 2 bars each side).
    """
    bars = _make_bars([
        ("100", "105"),   # 0
        ("95",  "100"),   # 1 - low candidate; k=1 OK, k=2 fails (no idx -1)
        ("96",  "100"),   # 2
        ("97",  "101"),   # 3
        ("96",  "100"),   # 4
        ("95",  "100"),   # 5 - low candidate; k=1 OK, k=2 fails (no idx 7)
        ("96",  "100"),   # 6
    ])
    res_k2 = detect_double_bottom(bars, level_threshold=Decimal("96"),
                                   min_separation=3, pivot_k=2)
    assert res_k2.pattern == Pattern.NONE
    res_k1 = detect_double_bottom(bars, level_threshold=Decimal("96"),
                                   min_separation=3, pivot_k=1)
    assert res_k1.pattern == Pattern.DOUBLE_BOTTOM
    assert res_k1.idx_1 == 1
    assert res_k1.idx_2 == 5


def test_double_top_rejected_when_highs_too_far_apart_in_pct():
    bars = _make_bars([
        ("99", "100"), ("100", "101"),
        ("100", "110"),                  # high 110
        ("99",  "104"), ("97", "100"), ("99", "104"), ("100", "104"),
        ("100", "105"),                  # high 105 -> diff > 1.5%
        ("99",  "104"), ("98", "103"),
    ])
    res = detect_double_top(bars, level_threshold=Decimal("104"))
    assert res.pattern == Pattern.NONE

"""Double-Top / Double-Bottom pattern detection.

Per MASTERPLAN Section 5: detect two local lows (for double-bottom) or two
local highs (for double-top) within a lookback window, satisfying:
  - max `max_pct_diff` price difference between the two extremes
  - min `min_separation` bars between them
  - both below `level_threshold` (for double-bottom; above for double-top)

Stateless: pass in a window of bars, get one PatternResult back.
Caller is responsible for sliding the window across history.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from .types import Bar, Pattern, PatternResult


_PIVOT_K = 2  # k-bar window: bars[idx] must be the lowest/highest in [idx-k, idx+k]


def _is_local_low(bars: Sequence[Bar], idx: int, k: int = _PIVOT_K) -> bool:
    """True if bars[idx].low is the strict minimum in the [idx-k, idx+k] window.

    Definition (Option B, k=2 default):
      - Requires k bars before AND k bars after, else returns False.
      - Strict `<` against all 2k neighbors. Bars with mathematically equal lows
        (common at crypto round-numbers like 60000.00) do NOT count as pivots.
        This is intentional: equal-low ambiguity should not generate signals.
    """
    if idx < k or idx >= len(bars) - k:
        return False
    lo = bars[idx].low
    for offset in range(-k, k + 1):
        if offset == 0:
            continue
        if bars[idx + offset].low <= lo:
            return False
    return True


def _is_local_high(bars: Sequence[Bar], idx: int, k: int = _PIVOT_K) -> bool:
    """Mirror of _is_local_low for highs (strict `>` over [idx-k, idx+k])."""
    if idx < k or idx >= len(bars) - k:
        return False
    hi = bars[idx].high
    for offset in range(-k, k + 1):
        if offset == 0:
            continue
        if bars[idx + offset].high >= hi:
            return False
    return True


def detect_double_bottom(
    bars: Sequence[Bar],
    level_threshold: Decimal,
    max_pct_diff: Decimal = Decimal("0.015"),
    min_separation: int = 3,
    pivot_k: int = _PIVOT_K,
) -> PatternResult:
    """Detect a double-bottom pattern in the given bar window.

    Args:
        bars: Window of bars, ascending by time. Typically `lookback_bars=15` long.
        level_threshold: Both lows must be <= this price (e.g., Camarilla L3).
        max_pct_diff: Max relative difference between the two lows (default 1.5%).
        min_separation: Min bars between the two lows (default 3).

    Returns:
        PatternResult with pattern=DOUBLE_BOTTOM (and the two indices, lows, neckline)
        if a valid pattern exists; otherwise pattern=NONE.

    If multiple valid pairs exist, the pair with the LATEST second-low is preferred
    (most recent signal); ties broken by lowest combined price.
    """
    if len(bars) < 3:
        return PatternResult(pattern=Pattern.NONE)

    # Find all local lows that are also at or below the threshold
    candidate_idxs = [
        i for i in range(1, len(bars) - 1)
        if bars[i].low <= level_threshold and _is_local_low(bars, i, k=pivot_k)
    ]

    best: PatternResult = PatternResult(pattern=Pattern.NONE)
    for j in range(len(candidate_idxs)):
        for i in range(j):
            idx_a, idx_b = candidate_idxs[i], candidate_idxs[j]
            if idx_b - idx_a < min_separation:
                continue
            low_a, low_b = bars[idx_a].low, bars[idx_b].low
            avg = (low_a + low_b) / Decimal("2")
            if avg == 0:
                continue
            pct_diff = abs(low_a - low_b) / avg
            if pct_diff > max_pct_diff:
                continue
            # Neckline = highest high BETWEEN the two lows (exclusive on both sides? no:
            # use interior bars only)
            between = bars[idx_a + 1: idx_b]
            if not between:
                continue
            neckline = max(b.high for b in between)
            candidate = PatternResult(
                pattern=Pattern.DOUBLE_BOTTOM,
                idx_1=idx_a, idx_2=idx_b,
                extreme_1=low_a, extreme_2=low_b,
                neckline=neckline,
            )
            # Prefer most recent second-low; on tie, lowest combined price.
            if best.pattern == Pattern.NONE:
                best = candidate
            elif (candidate.idx_2 or 0) > (best.idx_2 or 0):
                best = candidate
            elif (candidate.idx_2 == best.idx_2
                  and (low_a + low_b) < ((best.extreme_1 or Decimal(0)) + (best.extreme_2 or Decimal(0)))):
                best = candidate
    return best


def detect_double_top(
    bars: Sequence[Bar],
    level_threshold: Decimal,
    max_pct_diff: Decimal = Decimal("0.015"),
    min_separation: int = 3,
    pivot_k: int = _PIVOT_K,
) -> PatternResult:
    """Detect a double-top pattern. Mirror of detect_double_bottom.

    `level_threshold` is the minimum price both highs must reach (e.g., Camarilla H3).
    Neckline = lowest low between the two highs.
    """
    if len(bars) < 3:
        return PatternResult(pattern=Pattern.NONE)

    candidate_idxs = [
        i for i in range(1, len(bars) - 1)
        if bars[i].high >= level_threshold and _is_local_high(bars, i, k=pivot_k)
    ]

    best: PatternResult = PatternResult(pattern=Pattern.NONE)
    for j in range(len(candidate_idxs)):
        for i in range(j):
            idx_a, idx_b = candidate_idxs[i], candidate_idxs[j]
            if idx_b - idx_a < min_separation:
                continue
            high_a, high_b = bars[idx_a].high, bars[idx_b].high
            avg = (high_a + high_b) / Decimal("2")
            if avg == 0:
                continue
            pct_diff = abs(high_a - high_b) / avg
            if pct_diff > max_pct_diff:
                continue
            between = bars[idx_a + 1: idx_b]
            if not between:
                continue
            neckline = min(b.low for b in between)
            candidate = PatternResult(
                pattern=Pattern.DOUBLE_TOP,
                idx_1=idx_a, idx_2=idx_b,
                extreme_1=high_a, extreme_2=high_b,
                neckline=neckline,
            )
            if best.pattern == Pattern.NONE:
                best = candidate
            elif (candidate.idx_2 or 0) > (best.idx_2 or 0):
                best = candidate
            elif (candidate.idx_2 == best.idx_2
                  and (high_a + high_b) > ((best.extreme_1 or Decimal(0)) + (best.extreme_2 or Decimal(0)))):
                best = candidate
    return best

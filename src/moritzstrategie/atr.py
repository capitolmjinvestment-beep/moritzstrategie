"""Average True Range (ATR), Wilder smoothing.

True Range definition (per Wilder, 1978):
    TR_i = max( high_i - low_i,
                |high_i - close_{i-1}|,
                |low_i  - close_{i-1}| )

The 2nd and 3rd terms capture gap-up / gap-down moves that intra-bar range alone misses.

Seed and smoothing identical to RSI: SMA seed at i=period, then Wilder smoothing.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, Sequence

from .types import Bar


def compute_atr(bars: Sequence[Bar], period: int = 14) -> list[Optional[Decimal]]:
    """Compute Wilder-ATR for a sequence of bars.

    Args:
        bars: Bars ascending by time.
        period: ATR period (default 14).

    Returns:
        List of length len(bars). First `period` values are None
        (insufficient data), the rest are Decimal ATR values.
    """
    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")

    n = len(bars)
    out: list[Optional[Decimal]] = [None] * n
    if n <= period:
        return out

    # True Range at i requires close[i-1]; tr[0] is undefined -> skip
    trs: list[Decimal] = []
    for i in range(1, n):
        h, l, prev_c = bars[i].high, bars[i].low, bars[i - 1].close
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    # trs[k] corresponds to bars[k+1]

    period_d = Decimal(period)
    prev_smooth = period_d - Decimal("1")

    # Seed: SMA of first `period` TRs (trs[0..period-1], = bars[1..period])
    seed_sum = sum(trs[:period], start=Decimal("0"))
    atr = seed_sum / period_d
    out[period] = atr

    for k in range(period, len(trs)):
        atr = (atr * prev_smooth + trs[k]) / period_d
        out[k + 1] = atr

    return out

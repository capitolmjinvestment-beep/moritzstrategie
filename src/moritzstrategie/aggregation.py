"""H4 -> Daily bar aggregation.

Look-Ahead-Bias hotspot: this is THE function where future-leakage typically
sneaks into Camarilla strategies. The contract is strict:

    aggregate_to_daily(h4_bars) returns ONLY fully-completed UTC days.

If the most recent h4_bars only cover part of today (e.g., only bars 00:00, 04:00,
08:00), today is OMITTED from the output. Camarilla for tomorrow will use the
output of this function, which by construction contains no leakage.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from .types import Bar


def aggregate_to_daily(h4_bars: Sequence[Bar]) -> list[Bar]:
    """Aggregate 4h bars into completed daily bars (UTC).

    Rules:
      - Input must be sorted ascending by ts and contain only 4h bars.
      - A day is COMPLETE only if all 6 bars (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)
        are present. Incomplete days are silently dropped.
      - Daily bar's ts = 00:00 UTC of that calendar day.
      - O = open of 00:00 bar, C = close of 20:00 bar, H = max(highs), L = min(lows),
        V = sum(volumes).
    """
    if not h4_bars:
        return []

    # Verify sorted ascending
    for i in range(1, len(h4_bars)):
        if h4_bars[i].ts <= h4_bars[i - 1].ts:
            raise ValueError(
                f"h4_bars must be strictly ascending by ts; "
                f"bar[{i-1}].ts={h4_bars[i-1].ts}, bar[{i}].ts={h4_bars[i].ts}"
            )

    # Bucket by UTC calendar day
    buckets: dict[datetime, list[Bar]] = {}
    expected_hours = {0, 4, 8, 12, 16, 20}
    for bar in h4_bars:
        if bar.ts.tzinfo is None or bar.ts.utcoffset() != timedelta(0):
            raise ValueError(f"bar.ts must be UTC, got {bar.ts.tzinfo}")
        if bar.ts.hour not in expected_hours or bar.ts.minute != 0 or bar.ts.second != 0:
            raise ValueError(
                f"bar.ts must align to 4h grid (00/04/08/12/16/20:00 UTC), got {bar.ts}"
            )
        day_start = datetime.combine(bar.ts.date(), time(0, 0), tzinfo=timezone.utc)
        buckets.setdefault(day_start, []).append(bar)

    out: list[Bar] = []
    for day_start in sorted(buckets.keys()):
        bars = buckets[day_start]
        hours_present = {b.ts.hour for b in bars}
        if hours_present != expected_hours:
            # Incomplete day -> drop. This is the look-ahead guard.
            continue
        bars.sort(key=lambda b: b.ts)
        out.append(
            Bar(
                ts=day_start,
                open=bars[0].open,
                high=max(b.high for b in bars),
                low=min(b.low for b in bars),
                close=bars[-1].close,
                volume=sum((b.volume for b in bars), start=Decimal("0")),
            )
        )
    return out

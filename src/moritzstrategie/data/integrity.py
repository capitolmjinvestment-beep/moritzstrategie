"""Bar-data integrity checks.

Purpose: detect data quality issues BEFORE they corrupt indicator calculations.

A single bad bar in a 3-year history can:
  - Shift RSI seed mean (Wilder smoothing carries forward)
  - Make Camarilla levels wrong for an entire day
  - Cause false stop-fills in the backtest
  - Crash live trading at the worst moment

Checks performed:
  1. Ascending timestamps (strict, no duplicates)
  2. Exact bar-grid alignment (4h bars at 00/04/08/12/16/20 UTC; daily at 00 UTC)
  3. No gaps (every expected timestamp is present)
  4. OHLC sanity (low <= open/close <= high) — already enforced by Bar.__post_init__
     but re-check here in case bars were created via a different path
  5. Volume non-negative

All checks return a list of IntegrityIssue with severity + description.
Use `assert_clean()` for fail-fast in tests, or `report()` for production logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence

from ..types import Bar


class Severity(Enum):
    ERROR = "error"      # corrupts downstream calculations
    WARN = "warn"        # suspicious but not fatal (e.g., zero volume)


@dataclass(frozen=True)
class IntegrityIssue:
    severity: Severity
    code: str           # short tag for log aggregation
    message: str
    bar_idx: Optional[int] = None
    bar_ts: Optional[datetime] = None


# Bar-period in minutes for known granularities
GRANULARITY_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1H": 60, "4H": 240, "6H": 360, "12H": 720,
    "1D": 1440,
}


def check_integrity(
    bars: Sequence[Bar],
    granularity: str = "4H",
) -> list[IntegrityIssue]:
    """Run all integrity checks and return list of issues. Empty list = clean.

    Args:
        bars: Bars in ascending time order.
        granularity: One of GRANULARITY_MINUTES. Determines expected gap.

    Returns:
        List of IntegrityIssue. Empty if data is clean.
    """
    if granularity not in GRANULARITY_MINUTES:
        raise ValueError(f"unknown granularity {granularity!r}")
    issues: list[IntegrityIssue] = []
    if not bars:
        return issues

    period = timedelta(minutes=GRANULARITY_MINUTES[granularity])

    # 1) Bar-grid alignment for the first bar
    first = bars[0]
    if not _is_on_grid(first.ts, granularity):
        issues.append(IntegrityIssue(
            Severity.ERROR, "off_grid",
            f"first bar ts {first.ts} is not on the {granularity} grid",
            bar_idx=0, bar_ts=first.ts,
        ))

    for i, bar in enumerate(bars):
        # 4) OHLC sanity (Bar.__post_init__ enforces but re-check for safety)
        if bar.high < bar.low:
            issues.append(IntegrityIssue(
                Severity.ERROR, "ohlc_invalid",
                f"high {bar.high} < low {bar.low}", bar_idx=i, bar_ts=bar.ts,
            ))
        if not (bar.low <= bar.open <= bar.high):
            issues.append(IntegrityIssue(
                Severity.ERROR, "ohlc_invalid",
                f"open {bar.open} outside [low, high]", bar_idx=i, bar_ts=bar.ts,
            ))
        if not (bar.low <= bar.close <= bar.high):
            issues.append(IntegrityIssue(
                Severity.ERROR, "ohlc_invalid",
                f"close {bar.close} outside [low, high]", bar_idx=i, bar_ts=bar.ts,
            ))
        # 5) Volume sanity
        if bar.volume < 0:
            issues.append(IntegrityIssue(
                Severity.ERROR, "volume_negative",
                f"volume {bar.volume} < 0", bar_idx=i, bar_ts=bar.ts,
            ))
        elif bar.volume == 0:
            issues.append(IntegrityIssue(
                Severity.WARN, "volume_zero",
                "volume is zero (possible feed glitch or illiquid window)",
                bar_idx=i, bar_ts=bar.ts,
            ))

        if i == 0:
            continue
        prev = bars[i - 1]

        # 1) Strict ascending
        if bar.ts <= prev.ts:
            issues.append(IntegrityIssue(
                Severity.ERROR, "not_ascending",
                f"ts {bar.ts} <= prev ts {prev.ts}", bar_idx=i, bar_ts=bar.ts,
            ))
            continue  # gap check meaningless if order is wrong

        # 2) Grid alignment
        if not _is_on_grid(bar.ts, granularity):
            issues.append(IntegrityIssue(
                Severity.ERROR, "off_grid",
                f"ts {bar.ts} not on {granularity} grid",
                bar_idx=i, bar_ts=bar.ts,
            ))

        # 3) Gap detection
        gap = bar.ts - prev.ts
        if gap != period:
            n_missing = int(gap.total_seconds() / period.total_seconds()) - 1
            issues.append(IntegrityIssue(
                Severity.ERROR, "gap",
                f"gap of {gap} between bar {i-1} ({prev.ts}) and "
                f"bar {i} ({bar.ts}); expected {period}; {n_missing} bars missing",
                bar_idx=i, bar_ts=bar.ts,
            ))

    return issues


def assert_clean(bars: Sequence[Bar], granularity: str = "4H") -> None:
    """Raise if any ERROR-severity issue is present. Pass on warns."""
    issues = check_integrity(bars, granularity)
    errors = [i for i in issues if i.severity == Severity.ERROR]
    if errors:
        msg = f"{len(errors)} integrity error(s):\n" + "\n".join(
            f"  [{i.code}] {i.message}" for i in errors[:10]
        )
        if len(errors) > 10:
            msg += f"\n  ... and {len(errors) - 10} more"
        raise ValueError(msg)


def report(bars: Sequence[Bar], granularity: str = "4H") -> dict:
    """Summary statistics + issue counts. For logging or dashboard."""
    issues = check_integrity(bars, granularity)
    by_code: dict[str, int] = {}
    for issue in issues:
        by_code[issue.code] = by_code.get(issue.code, 0) + 1
    return {
        "n_bars": len(bars),
        "first_ts": bars[0].ts if bars else None,
        "last_ts": bars[-1].ts if bars else None,
        "issues_total": len(issues),
        "errors": sum(1 for i in issues if i.severity == Severity.ERROR),
        "warnings": sum(1 for i in issues if i.severity == Severity.WARN),
        "by_code": by_code,
    }


def _is_on_grid(ts: datetime, granularity: str) -> bool:
    """Check if `ts` aligns with the expected bar boundaries.

    For 4h: hour in {0, 4, 8, 12, 16, 20}, minute/second = 0.
    For 1H: minute/second = 0.
    For 1D: hour/minute/second = 0.
    """
    if ts.second != 0 or ts.microsecond != 0:
        return False
    minutes = GRANULARITY_MINUTES[granularity]
    if minutes < 60:
        return ts.second == 0 and ts.microsecond == 0 and (ts.minute % minutes == 0)
    if ts.minute != 0:
        return False
    if minutes == 60:
        return True
    hours = minutes // 60
    if minutes == 1440:  # daily
        return ts.hour == 0
    # 4H/6H/12H: hour must be multiple of `hours`
    return ts.hour % hours == 0

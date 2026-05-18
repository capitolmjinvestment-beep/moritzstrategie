"""Shared types for indicator modules.

Decimal everywhere (per CLAUDE.md): prices and volumes use Decimal,
never float. Float rounding has cost traders seven-figure amounts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class Bar:
    """OHLCV bar. Immutable.

    `ts` is the bar's OPEN time in UTC. A 4h bar with ts=12:00 covers 12:00-16:00.
    A daily bar with ts=00:00 covers 00:00-24:00 of that calendar day (UTC).
    """

    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError(f"Bar.ts must be timezone-aware (UTC), got naive: {self.ts}")
        if self.high < self.low:
            raise ValueError(f"Bar.high ({self.high}) < Bar.low ({self.low})")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"Bar.open {self.open} outside [low, high] = [{self.low}, {self.high}]")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"Bar.close {self.close} outside [low, high] = [{self.low}, {self.high}]")
        # Reject feed glitches that would cause divide-by-zero downstream
        # (e.g., Trade.pnl_pct, double-bottom pct_diff). Real crypto prices are > 0.
        if self.low <= Decimal("0"):
            raise ValueError(f"Bar.low must be > 0 (feed glitch?), got {self.low}")
        if self.volume < Decimal("0"):
            raise ValueError(f"Bar.volume must be >= 0, got {self.volume}")


class Pattern(Enum):
    NONE = "none"
    DOUBLE_TOP = "double_top"
    DOUBLE_BOTTOM = "double_bottom"


@dataclass(frozen=True)
class PatternResult:
    """Result of pattern detection at a given bar.

    For DOUBLE_TOP: `extreme_1`/`extreme_2` are the two top highs (Decimal prices),
    `neckline` is the intermediate LOW between them (Decimal).
    For DOUBLE_BOTTOM: extremes are the two bottom lows, neckline is the intermediate HIGH.
    For NONE: all extra fields are None.

    Indices (`idx_1`, `idx_2`) are positions in the input window, 0-based.
    """

    pattern: Pattern
    idx_1: Optional[int] = None
    idx_2: Optional[int] = None
    extreme_1: Optional[Decimal] = None
    extreme_2: Optional[Decimal] = None
    neckline: Optional[Decimal] = None

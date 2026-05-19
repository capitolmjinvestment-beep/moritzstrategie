"""Fibonacci retracement and extension levels.

Per the user's "clean charts" philosophy: Fibonacci is computed mathematically
from a swing range (swing_low, swing_high) and exposed as named levels.
The strategy chooses which levels to use as TP / SL anchors.

Standard retracement levels (% of range pulled back from extreme):
    0.000  - swing extreme (start of retracement)
    0.236  - shallow retracement
    0.382  - common retracement target
    0.500  - midpoint (not Fibonacci but commonly drawn)
    0.618  - golden ratio retracement
    0.786  - deep retracement (last support before invalidation)
    1.000  - swing origin (full retracement)

Extension levels (beyond the swing in the same direction):
    1.272  - first extension
    1.618  - golden extension
    2.000  - double the swing
    2.618  - second golden

Use cases in this codebase:
  - Long entry from swing low: TP1 at 0.618 retracement of the prior down-leg,
    TP2 at 1.272 extension of the up-move.
  - Trailing stop: ratchet stop up to 0.382 retracement of the running profit.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class SwingDirection(Enum):
    UP = "up"        # swing from low to high; retracement = pullback from high toward low
    DOWN = "down"    # swing from high to low; retracement = bounce from low toward high


# Canonical retracement and extension ratios as Decimals (exact).
RETRACEMENT_RATIOS: tuple[Decimal, ...] = (
    Decimal("0.000"),
    Decimal("0.236"),
    Decimal("0.382"),
    Decimal("0.500"),
    Decimal("0.618"),
    Decimal("0.786"),
    Decimal("1.000"),
)

EXTENSION_RATIOS: tuple[Decimal, ...] = (
    Decimal("1.272"),
    Decimal("1.618"),
    Decimal("2.000"),
    Decimal("2.618"),
)


@dataclass(frozen=True)
class FibonacciLevels:
    """Computed retracement + extension levels for a single swing.

    For an UP swing (low -> high):
      - retracement[0.000] = swing_high
      - retracement[1.000] = swing_low
      - retracement[r] = swing_high - r * (swing_high - swing_low)
      - extension[e] = swing_high + (e - 1) * (swing_high - swing_low)

    For a DOWN swing (high -> low):
      - retracement[0.000] = swing_low
      - retracement[1.000] = swing_high
      - retracement[r] = swing_low + r * (swing_high - swing_low)
      - extension[e] = swing_low - (e - 1) * (swing_high - swing_low)
    """
    direction: SwingDirection
    swing_low: Decimal
    swing_high: Decimal
    retracements: dict[Decimal, Decimal]
    extensions: dict[Decimal, Decimal]

    @property
    def range(self) -> Decimal:
        return self.swing_high - self.swing_low

    def retracement(self, ratio: Decimal) -> Decimal:
        """Price at a given retracement ratio (interpolated if not in canonical set)."""
        if ratio in self.retracements:
            return self.retracements[ratio]
        return _compute_retracement(self.direction, self.swing_low, self.swing_high, ratio)

    def extension(self, ratio: Decimal) -> Decimal:
        if ratio in self.extensions:
            return self.extensions[ratio]
        return _compute_extension(self.direction, self.swing_low, self.swing_high, ratio)


def compute_fibonacci(
    swing_low: Decimal,
    swing_high: Decimal,
    direction: SwingDirection,
) -> FibonacciLevels:
    """Build a FibonacciLevels for the given swing.

    Args:
        swing_low: The lower price of the swing (always <= swing_high).
        swing_high: The upper price of the swing.
        direction: UP if the swing was a rally, DOWN if it was a decline.

    Returns:
        FibonacciLevels with all canonical retracements + extensions pre-computed.

    Raises:
        ValueError: if swing_high <= swing_low or either is non-positive.
    """
    if swing_low <= 0 or swing_high <= 0:
        raise ValueError(f"prices must be > 0, got low={swing_low} high={swing_high}")
    if swing_high <= swing_low:
        raise ValueError(f"swing_high ({swing_high}) must be > swing_low ({swing_low})")
    retracements = {
        r: _compute_retracement(direction, swing_low, swing_high, r)
        for r in RETRACEMENT_RATIOS
    }
    extensions = {
        e: _compute_extension(direction, swing_low, swing_high, e)
        for e in EXTENSION_RATIOS
    }
    return FibonacciLevels(
        direction=direction,
        swing_low=swing_low,
        swing_high=swing_high,
        retracements=retracements,
        extensions=extensions,
    )


def _compute_retracement(
    direction: SwingDirection, swing_low: Decimal, swing_high: Decimal, ratio: Decimal,
) -> Decimal:
    rng = swing_high - swing_low
    if direction == SwingDirection.UP:
        return swing_high - ratio * rng
    return swing_low + ratio * rng


def _compute_extension(
    direction: SwingDirection, swing_low: Decimal, swing_high: Decimal, ratio: Decimal,
) -> Decimal:
    rng = swing_high - swing_low
    if direction == SwingDirection.UP:
        return swing_high + (ratio - Decimal("1")) * rng
    return swing_low - (ratio - Decimal("1")) * rng

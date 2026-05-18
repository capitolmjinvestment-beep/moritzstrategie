"""Camarilla pivot levels.

Formula (classic Camarilla, see MASTERPLAN Section 4):

    R = H - L
    H4 = C + R * 1.1/2
    H3 = C + R * 1.1/4   <- short-reversal level
    H2 = C + R * 1.1/6
    H1 = C + R * 1.1/12
    P  = (H + L + C) / 3
    L1 = C - R * 1.1/12
    L2 = C - R * 1.1/6
    L3 = C - R * 1.1/4   <- long-reversal level
    L4 = C - R * 1.1/2

Levels for day T are computed from the COMPLETED daily bar of day T-1.
Stateless: pass in the prior daily bar, get the level dict back.
"""

from __future__ import annotations

from decimal import Decimal

from .types import Bar

# Camarilla multipliers (1.1 / divisor)
_MULT_4 = Decimal("1.1") / Decimal("2")    # 0.55
_MULT_3 = Decimal("1.1") / Decimal("4")    # 0.275
_MULT_2 = Decimal("1.1") / Decimal("6")
_MULT_1 = Decimal("1.1") / Decimal("12")
_THREE = Decimal("3")


def compute_camarilla(prior_daily_bar: Bar) -> dict[str, Decimal]:
    """Compute Camarilla pivot levels for the next trading day.

    Args:
        prior_daily_bar: The COMPLETED daily bar of day T-1. Caller is responsible
            for ensuring this is actually a completed day (use aggregate_to_daily()).

    Returns:
        Dict with keys: 'H4', 'H3', 'H2', 'H1', 'P', 'L1', 'L2', 'L3', 'L4'.
        All values are Decimal.
    """
    h = prior_daily_bar.high
    l = prior_daily_bar.low
    c = prior_daily_bar.close
    r = h - l

    return {
        "H4": c + r * _MULT_4,
        "H3": c + r * _MULT_3,
        "H2": c + r * _MULT_2,
        "H1": c + r * _MULT_1,
        "P": (h + l + c) / _THREE,
        "L1": c - r * _MULT_1,
        "L2": c - r * _MULT_2,
        "L3": c - r * _MULT_3,
        "L4": c - r * _MULT_4,
    }

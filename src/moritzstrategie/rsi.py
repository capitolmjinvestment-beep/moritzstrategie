"""Relative Strength Index (RSI), Wilder smoothing.

Why Wilder, not SMA: Wilder's exponential smoothing is the canonical RSI used
by every charting platform (TradingView, MT4/5, ta-lib, Bitget). If we used
SMA-based RSI, our signals would diverge from anything the user sees on screen,
which makes debugging Phase 5 paper trading impossible.

Formula:
    delta_i        = close[i] - close[i-1]
    gain_i         = max(delta_i, 0)
    loss_i         = max(-delta_i, 0)

    Seed (at i = period):
        avg_gain   = mean(gain_1 .. gain_period)
        avg_loss   = mean(loss_1 .. loss_period)

    Wilder smoothing (for i > period):
        avg_gain_i = (avg_gain_{i-1} * (period-1) + gain_i) / period
        avg_loss_i = (avg_loss_{i-1} * (period-1) + loss_i) / period

    rsi_i = 100 - 100 / (1 + avg_gain_i / avg_loss_i)
          = 100                                   if avg_loss == 0
          = 0                                     if avg_gain == 0 and avg_loss > 0
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, Sequence


_HUNDRED = Decimal("100")


def compute_rsi(closes: Sequence[Decimal], period: int = 14) -> list[Optional[Decimal]]:
    """Compute Wilder-RSI for a sequence of closes.

    Args:
        closes: Decimal close prices, ascending by time.
        period: RSI period (default 14).

    Returns:
        List of length len(closes). First `period` values are None
        (insufficient data to compute), the rest are Decimal in [0, 100].
    """
    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")

    n = len(closes)
    out: list[Optional[Decimal]] = [None] * n
    if n <= period:
        return out

    period_d = Decimal(period)
    prev_smooth = period_d - Decimal("1")

    # Seed: SMA of first `period` gains/losses (deltas from i=1..period)
    sum_gain = Decimal("0")
    sum_loss = Decimal("0")
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta > 0:
            sum_gain += delta
        elif delta < 0:
            sum_loss += -delta
    avg_gain = sum_gain / period_d
    avg_loss = sum_loss / period_d
    out[period] = _rsi_from_avgs(avg_gain, avg_loss)

    # Wilder smoothing onwards
    for i in range(period + 1, n):
        delta = closes[i] - closes[i - 1]
        gain = delta if delta > 0 else Decimal("0")
        loss = -delta if delta < 0 else Decimal("0")
        avg_gain = (avg_gain * prev_smooth + gain) / period_d
        avg_loss = (avg_loss * prev_smooth + loss) / period_d
        out[i] = _rsi_from_avgs(avg_gain, avg_loss)

    return out


def _rsi_from_avgs(avg_gain: Decimal, avg_loss: Decimal) -> Decimal:
    if avg_loss == 0:
        return _HUNDRED if avg_gain > 0 else Decimal("50")  # all flat -> neutral
    rs = avg_gain / avg_loss
    return _HUNDRED - _HUNDRED / (Decimal("1") + rs)

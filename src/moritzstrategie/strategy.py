"""Entry-signal logic for the H4 Camarilla Reversal strategy.

Pure function: takes a window of bars + precomputed Camarilla levels,
returns an EntrySignal or None. No I/O, no state, no side effects.

Implements MASTERPLAN Section 5 (entries) and Section 6 (TP/SL placement).
The Strategy.on_bar() in the real repo will call this and translate the result
into exchange orders.

LOOK-AHEAD CONTRACT: evaluate_entry(bars, current_idx, ...) MUST use bars[:current_idx+1]
only. The current bar is treated as just-closed. The test
`test_evaluate_entry_no_lookahead` proves this.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence

from .patterns import detect_double_bottom, detect_double_top
from .rsi import compute_rsi
from .atr import compute_atr
from .types import Bar, Pattern


class Side(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class EntrySignal:
    side: Side
    entry_price: Decimal      # close of trigger bar
    stop_price: Decimal       # MASTERPLAN Section 6: min(DB lows) - 0.5*ATR (long)
    tp1_price: Decimal        # central pivot P, close 50%
    tp2_price: Decimal        # long -> H3, short -> L3, close remaining 50%
    trigger_idx: int          # bar index where signal fired


# ---- Tunable thresholds (defaults match MASTERPLAN) ----

@dataclass(frozen=True)
class EntryParams:
    rsi_period: int = 14
    rsi_oversold: Decimal = Decimal("30")
    rsi_overbought: Decimal = Decimal("70")
    atr_period: int = 14
    stop_atr_mult: Decimal = Decimal("0.5")
    pivot_touch_lookback: int = 5        # MASTERPLAN: "in den letzten 5 Bars"
    rsi_extreme_lookback: int = 3        # MASTERPLAN: "innerhalb der letzten 3 Bars"
    pattern_lookback: int = 15
    pattern_max_pct_diff: Decimal = Decimal("0.015")
    pattern_min_separation: int = 3
    pivot_k: int = 2                      # bars of forward/backward confirmation for pivot;
                                          # 1=looser (more patterns), 2=default, 3=stricter


def evaluate_entry(
    bars: Sequence[Bar],
    current_idx: int,
    camarilla: dict[str, Decimal],
    params: EntryParams = EntryParams(),
) -> Optional[EntrySignal]:
    """Check whether the just-closed bar at `current_idx` produces an entry signal.

    Args:
        bars: All bars ascending by time. Function uses bars[: current_idx + 1] only.
        current_idx: Index of the just-closed bar.
        camarilla: Today's Camarilla levels. Must contain at least 'H3', 'L3', 'P'.
            Caller is responsible for ensuring these are derived from yesterday's
            daily bar (use aggregate_to_daily + compute_camarilla upstream).
        params: Thresholds; defaults match MASTERPLAN Section 5.

    Returns:
        EntrySignal if all 4 conditions match for LONG or SHORT, else None.
        If both LONG and SHORT match in the same bar (very unlikely): LONG wins.
    """
    if current_idx < 0 or current_idx >= len(bars):
        return None

    # Work with the causal window only
    window = list(bars[: current_idx + 1])
    n = len(window)

    # Need enough history for RSI/ATR/pattern lookback
    min_history = max(
        params.rsi_period + 1,
        params.atr_period + 1,
        params.pattern_lookback,
    )
    if n < min_history:
        return None

    closes = [b.close for b in window]
    rsi = compute_rsi(closes, period=params.rsi_period)
    atr = compute_atr(window, period=params.atr_period)

    cur_rsi = rsi[current_idx]
    cur_atr = atr[current_idx]
    if cur_rsi is None or cur_atr is None:
        return None

    long_signal = _try_long(window, current_idx, camarilla, params, rsi, cur_atr)
    if long_signal is not None:
        return long_signal
    return _try_short(window, current_idx, camarilla, params, rsi, cur_atr)


# ---------------- LONG ----------------

def _try_long(
    window: list[Bar],
    idx: int,
    cam: dict[str, Decimal],
    p: EntryParams,
    rsi: list[Optional[Decimal]],
    cur_atr: Decimal,
) -> Optional[EntrySignal]:
    l3 = cam.get("L3")
    h3 = cam.get("H3")
    pivot_p = cam.get("P")
    if l3 is None or h3 is None or pivot_p is None:
        return None

    # Cond 1: Pivot-Touch: any close <= L3 within the last `pivot_touch_lookback` bars
    touch_start = max(0, idx - p.pivot_touch_lookback + 1)
    if not any(window[j].close <= l3 for j in range(touch_start, idx + 1)):
        return None

    # Cond 2: RSI was below oversold within last `rsi_extreme_lookback` bars
    rsi_start = max(0, idx - p.rsi_extreme_lookback + 1)
    rsi_window = [rsi[j] for j in range(rsi_start, idx + 1) if rsi[j] is not None]
    if not any(v < p.rsi_oversold for v in rsi_window if v is not None):
        return None

    # Cond 3: Double-Bottom pattern in last `pattern_lookback` bars at/below L3
    pat_start = max(0, idx - p.pattern_lookback + 1)
    pat_bars = window[pat_start: idx + 1]
    pattern_res = detect_double_bottom(
        pat_bars,
        level_threshold=l3,
        max_pct_diff=p.pattern_max_pct_diff,
        min_separation=p.pattern_min_separation,
        pivot_k=p.pivot_k,
    )
    if pattern_res.pattern != Pattern.DOUBLE_BOTTOM:
        return None

    # Cond 4: Current bar closes ABOVE neckline (intermediate high) AND RSI > oversold
    cur_close = window[idx].close
    cur_rsi = rsi[idx]
    if cur_rsi is None or pattern_res.neckline is None:
        return None
    if not (cur_close > pattern_res.neckline and cur_rsi > p.rsi_oversold):
        return None

    # Stop = min(DB lows) - stop_atr_mult * ATR
    low1, low2 = pattern_res.extreme_1, pattern_res.extreme_2
    if low1 is None or low2 is None:
        return None
    stop_price = min(low1, low2) - p.stop_atr_mult * cur_atr

    return EntrySignal(
        side=Side.LONG,
        entry_price=cur_close,
        stop_price=stop_price,
        tp1_price=pivot_p,
        tp2_price=h3,
        trigger_idx=idx,
    )


# ---------------- SHORT ----------------

def _try_short(
    window: list[Bar],
    idx: int,
    cam: dict[str, Decimal],
    p: EntryParams,
    rsi: list[Optional[Decimal]],
    cur_atr: Decimal,
) -> Optional[EntrySignal]:
    l3 = cam.get("L3")
    h3 = cam.get("H3")
    pivot_p = cam.get("P")
    if l3 is None or h3 is None or pivot_p is None:
        return None

    touch_start = max(0, idx - p.pivot_touch_lookback + 1)
    if not any(window[j].close >= h3 for j in range(touch_start, idx + 1)):
        return None

    rsi_start = max(0, idx - p.rsi_extreme_lookback + 1)
    rsi_window = [rsi[j] for j in range(rsi_start, idx + 1) if rsi[j] is not None]
    if not any(v > p.rsi_overbought for v in rsi_window if v is not None):
        return None

    pat_start = max(0, idx - p.pattern_lookback + 1)
    pat_bars = window[pat_start: idx + 1]
    pattern_res = detect_double_top(
        pat_bars,
        level_threshold=h3,
        max_pct_diff=p.pattern_max_pct_diff,
        min_separation=p.pattern_min_separation,
        pivot_k=p.pivot_k,
    )
    if pattern_res.pattern != Pattern.DOUBLE_TOP:
        return None

    cur_close = window[idx].close
    cur_rsi = rsi[idx]
    if cur_rsi is None or pattern_res.neckline is None:
        return None
    if not (cur_close < pattern_res.neckline and cur_rsi < p.rsi_overbought):
        return None

    high1, high2 = pattern_res.extreme_1, pattern_res.extreme_2
    if high1 is None or high2 is None:
        return None
    stop_price = max(high1, high2) + p.stop_atr_mult * cur_atr

    return EntrySignal(
        side=Side.SHORT,
        entry_price=cur_close,
        stop_price=stop_price,
        tp1_price=pivot_p,
        tp2_price=l3,
        trigger_idx=idx,
    )

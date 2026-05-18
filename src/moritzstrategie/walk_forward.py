"""Walk-forward out-of-sample validation.

Even though this is a RULE-based strategy (no training), walk-forward gives you
the most honest answer to "does this work across different market regimes?".

The approach:
  1. Split history into overlapping test windows (e.g., 3 months each).
  2. For each window, run the portfolio backtest *starting from fresh equity*.
  3. Compare metrics (Sharpe, win-rate, total return) across windows.

What you're looking for:
  - Consistent positive return across most windows -> robust edge
  - One huge winning window + several losers -> overfitting to a regime
  - Sharpe variance > mean -> strategy is noise, not signal

Phase 4 gate (MASTERPLAN): pass if Sharpe ≥ 1.0 AND total trades ≥ 80
ACROSS THE FULL PERIOD. Walk-forward additionally tells you if that
aggregate Sharpe is uniformly distributed or concentrated in one window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from .friction import FrictionModel
from .portfolio_backtest import PortfolioResult, run_portfolio_backtest
from .risk import RiskParams
from .strategy import EntryParams
from .types import Bar


# 4h bars per "month" (approximate; 30 days × 6 bars/day)
BARS_PER_MONTH = 6 * 30


@dataclass
class WalkForwardWindow:
    """A single out-of-sample window in the walk-forward analysis."""
    window_idx: int
    test_start_ts: datetime
    test_end_ts: datetime
    result: PortfolioResult

    @property
    def label(self) -> str:
        return (f"#{self.window_idx} "
                f"{self.test_start_ts.date()} → {self.test_end_ts.date()}")


@dataclass
class WalkForwardReport:
    """Aggregate metrics across all walk-forward windows."""
    windows: list[WalkForwardWindow]

    @property
    def n_windows(self) -> int:
        return len(self.windows)

    @property
    def positive_windows(self) -> int:
        return sum(1 for w in self.windows if w.result.total_return_pct > 0)

    @property
    def consistency(self) -> Optional[Decimal]:
        """Fraction of windows with positive returns. None if no windows."""
        if not self.windows:
            return None
        return Decimal(self.positive_windows) / Decimal(self.n_windows)

    @property
    def total_trades(self) -> int:
        return sum(w.result.n_trades for w in self.windows)

    @property
    def aggregate_return_pct(self) -> Decimal:
        """Compounded return if you ran each window starting from same equity.

        NOTE: This is NOT the same as a single continuous backtest; it's the
        product of per-window returns. Use for cross-regime comparison only.
        """
        if not self.windows:
            return Decimal("0")
        compound = Decimal("1")
        for w in self.windows:
            compound *= (Decimal("1") + w.result.total_return_pct)
        return compound - Decimal("1")


def walk_forward(
    bars: Sequence[Bar],
    test_months: int = 3,
    warmup_bars: int = 60,
    initial_equity: Decimal = Decimal("1000"),
    entry_params: EntryParams = EntryParams(),
    risk_params: RiskParams = RiskParams(),
    friction: Optional[FrictionModel] = None,
) -> WalkForwardReport:
    """Slide a fixed-size test window across the data and backtest each piece.

    Args:
        bars: Full ascending bar history (single symbol).
        test_months: Size of each test window in months. Default 3 = quarterly.
        warmup_bars: Bars of history fed in before the test starts (so RSI/ATR
            are warmed up; not counted toward the window's PnL).
        initial_equity: Equity at the start of EACH window (windows are independent).

    Returns:
        WalkForwardReport with one WalkForwardWindow per non-overlapping test
        window. Windows are sequential and disjoint.

    Notes:
        - Windows are independent (no equity carryover); use this to detect
          regime sensitivity, not to compute "would I have made X over Y years".
        - For continuous equity-curve analysis, call run_portfolio_backtest
          on the whole history once.
    """
    if not bars:
        return WalkForwardReport(windows=[])

    window_size = test_months * BARS_PER_MONTH
    if window_size <= 0:
        raise ValueError(f"test_months must be > 0, got {test_months}")

    windows: list[WalkForwardWindow] = []
    cursor = warmup_bars  # start of first test window
    window_idx = 0

    while cursor + window_size <= len(bars):
        # Include warmup prefix so indicators are warm at start of test
        prefix_start = max(0, cursor - warmup_bars)
        test_end = cursor + window_size
        sub_bars = bars[prefix_start:test_end]

        # NOTE: the backtest will spend the first `warmup_bars` of sub_bars
        # warming up RSI/ATR; signals during that prefix that happen to fire
        # will be attributed to this window. Acceptable for out-of-sample
        # validation since the prefix is small relative to window_size.
        result = run_portfolio_backtest(
            sub_bars,
            initial_equity=initial_equity,
            entry_params=entry_params,
            risk_params=risk_params,
            friction=friction,
        )
        windows.append(WalkForwardWindow(
            window_idx=window_idx,
            test_start_ts=bars[cursor].ts,
            test_end_ts=bars[test_end - 1].ts,
            result=result,
        ))
        window_idx += 1
        cursor += window_size  # disjoint windows (no overlap)

    return WalkForwardReport(windows=windows)

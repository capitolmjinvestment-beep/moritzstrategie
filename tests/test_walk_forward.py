"""Tests for walk-forward validator."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from moritzstrategie.types import Bar
from moritzstrategie.walk_forward import BARS_PER_MONTH, walk_forward


UTC = timezone.utc


def _flat_bars(n: int) -> list[Bar]:
    return [
        Bar(
            ts=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=4 * i),
            open=Decimal("100"), high=Decimal("101"),
            low=Decimal("99"), close=Decimal("100"), volume=Decimal("1"),
        )
        for i in range(n)
    ]


def test_walk_forward_empty_input():
    report = walk_forward([])
    assert report.n_windows == 0
    assert report.aggregate_return_pct == Decimal("0")


def test_walk_forward_too_short_no_windows():
    """If history < warmup + 1 window, no windows produced."""
    bars = _flat_bars(50)  # less than warmup(60) + 1 month(180)
    report = walk_forward(bars, test_months=3, warmup_bars=60)
    assert report.n_windows == 0


def test_walk_forward_produces_expected_window_count():
    # 60 warmup + 4 × 1-month windows = 60 + 4*180 = 780 bars
    bars = _flat_bars(60 + 4 * BARS_PER_MONTH)
    report = walk_forward(bars, test_months=1, warmup_bars=60)
    assert report.n_windows == 4


def test_walk_forward_window_indices_sequential():
    bars = _flat_bars(60 + 3 * BARS_PER_MONTH)
    report = walk_forward(bars, test_months=1, warmup_bars=60)
    assert [w.window_idx for w in report.windows] == [0, 1, 2]


def test_walk_forward_windows_are_disjoint():
    bars = _flat_bars(60 + 3 * BARS_PER_MONTH)
    report = walk_forward(bars, test_months=1, warmup_bars=60)
    # Each test_end < next test_start (with the test_start being one bar after end)
    for prev, curr in zip(report.windows, report.windows[1:]):
        assert prev.test_end_ts < curr.test_start_ts


def test_walk_forward_flat_data_zero_trades_consistency_undefined_when_no_movement():
    bars = _flat_bars(60 + 2 * BARS_PER_MONTH)
    report = walk_forward(bars, test_months=1, warmup_bars=60)
    # 0 trades in flat data, but the windows themselves are produced.
    # All windows have return == 0 -> not positive -> consistency == 0/n
    assert report.total_trades == 0
    assert report.consistency == Decimal("0")


def test_walk_forward_aggregate_return_compound_math():
    """Manual construction: 3 hypothetical windows at +10%, -5%, +20% -> ~25.4%."""
    from moritzstrategie.portfolio_backtest import PortfolioResult
    from moritzstrategie.walk_forward import WalkForwardReport, WalkForwardWindow

    def mk_result(ret_pct: str) -> PortfolioResult:
        eq = Decimal("1000")
        fin = eq * (Decimal("1") + Decimal(ret_pct))
        return PortfolioResult(eq, fin, [], 0, {})

    windows = [
        WalkForwardWindow(0, datetime(2024, 1, 1, tzinfo=UTC),
                          datetime(2024, 4, 1, tzinfo=UTC), mk_result("0.10")),
        WalkForwardWindow(1, datetime(2024, 4, 2, tzinfo=UTC),
                          datetime(2024, 7, 1, tzinfo=UTC), mk_result("-0.05")),
        WalkForwardWindow(2, datetime(2024, 7, 2, tzinfo=UTC),
                          datetime(2024, 10, 1, tzinfo=UTC), mk_result("0.20")),
    ]
    report = WalkForwardReport(windows)
    # 1.10 * 0.95 * 1.20 - 1 = 0.254
    expected = Decimal("1.10") * Decimal("0.95") * Decimal("1.20") - Decimal("1")
    assert report.aggregate_return_pct == expected
    assert report.positive_windows == 2
    assert report.consistency == Decimal("2") / Decimal("3")


def test_walk_forward_rejects_invalid_test_months():
    bars = _flat_bars(200)
    with pytest.raises(ValueError, match="test_months must be > 0"):
        walk_forward(bars, test_months=0)

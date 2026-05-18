"""Tests for data-integrity checks."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from moritzstrategie.data.integrity import (
    Severity,
    assert_clean,
    check_integrity,
    report,
)
from moritzstrategie.types import Bar


UTC = timezone.utc


def _bar(idx: int, o="100", h="101", l="99", c="100", v="1") -> Bar:
    return Bar(
        ts=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=4 * idx),
        open=Decimal(o), high=Decimal(h),
        low=Decimal(l), close=Decimal(c), volume=Decimal(v),
    )


def test_check_integrity_empty_returns_empty():
    assert check_integrity([]) == []


def test_check_integrity_clean_4h_series():
    bars = [_bar(i) for i in range(10)]
    issues = check_integrity(bars, "4H")
    assert issues == []


def test_detects_gap():
    bars = [_bar(0), _bar(1), _bar(2), _bar(4)]  # bar 3 missing
    issues = check_integrity(bars, "4H")
    gap_issues = [i for i in issues if i.code == "gap"]
    assert len(gap_issues) == 1
    assert "1 bars missing" in gap_issues[0].message


def test_detects_duplicate_timestamp():
    bars = [_bar(0), _bar(1), _bar(1)]  # bar idx 1 twice
    issues = check_integrity(bars, "4H")
    nasc = [i for i in issues if i.code == "not_ascending"]
    assert len(nasc) == 1


def test_detects_off_grid():
    bar = Bar(
        ts=datetime(2025, 1, 1, 3, 0, tzinfo=UTC),  # 03:00 not on 4h grid
        open=Decimal("100"), high=Decimal("101"),
        low=Decimal("99"), close=Decimal("100"), volume=Decimal("1"),
    )
    issues = check_integrity([bar], "4H")
    assert any(i.code == "off_grid" for i in issues)


def test_zero_volume_is_warn_not_error():
    bars = [_bar(i, v="0") for i in range(3)]
    issues = check_integrity(bars, "4H")
    assert all(i.code == "volume_zero" for i in issues)
    assert all(i.severity == Severity.WARN for i in issues)


def test_assert_clean_passes_on_clean_series():
    bars = [_bar(i) for i in range(10)]
    assert_clean(bars, "4H")  # no exception


def test_assert_clean_raises_on_gap():
    bars = [_bar(0), _bar(2)]
    with pytest.raises(ValueError, match="integrity error"):
        assert_clean(bars, "4H")


def test_assert_clean_does_not_raise_on_warn_only():
    """Zero-volume is a warning; assert_clean accepts it."""
    bars = [_bar(i, v="0") for i in range(3)]
    assert_clean(bars, "4H")  # warns but does not raise


def test_report_returns_summary():
    bars = [_bar(0), _bar(1), _bar(3)]  # 1 gap
    r = report(bars, "4H")
    assert r["n_bars"] == 3
    assert r["errors"] == 1
    assert r["by_code"] == {"gap": 1}


def test_grid_check_for_1H():
    bars = [
        Bar(ts=datetime(2025, 1, 1, h, tzinfo=UTC),
            open=Decimal("100"), high=Decimal("101"),
            low=Decimal("99"), close=Decimal("100"), volume=Decimal("1"))
        for h in range(3)
    ]
    issues = check_integrity(bars, "1H")
    assert issues == []


def test_grid_check_for_1D():
    bars = [
        Bar(ts=datetime(2025, 1, i, tzinfo=UTC),
            open=Decimal("100"), high=Decimal("101"),
            low=Decimal("99"), close=Decimal("100"), volume=Decimal("1"))
        for i in range(1, 4)
    ]
    issues = check_integrity(bars, "1D")
    assert issues == []

"""Unit tests for Camarilla pivot computation."""

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from moritzstrategie.aggregation import aggregate_to_daily
from moritzstrategie.camarilla import compute_camarilla
from moritzstrategie.types import Bar


UTC = timezone.utc


def _bar(ts: datetime, o: str, h: str, l: str, c: str, v: str = "1") -> Bar:
    return Bar(ts=ts, open=Decimal(o), high=Decimal(h), low=Decimal(l),
               close=Decimal(c), volume=Decimal(v))


def _h4_day(date_str: str, ohlc_per_bar: list[tuple[str, str, str, str]]) -> list[Bar]:
    """Build 6 h4 bars for a full UTC day. date_str = 'YYYY-MM-DD'."""
    y, m, d = (int(x) for x in date_str.split("-"))
    hours = [0, 4, 8, 12, 16, 20]
    assert len(ohlc_per_bar) == 6
    return [
        _bar(datetime(y, m, d, h, tzinfo=UTC), o, hi, lo, c)
        for h, (o, hi, lo, c) in zip(hours, ohlc_per_bar)
    ]


# ---------- compute_camarilla ----------

def test_camarilla_known_values():
    """Hand-calculated reference case."""
    # H=110, L=90, C=100  =>  R=20
    bar = _bar(datetime(2025, 1, 1, tzinfo=UTC), "95", "110", "90", "100")
    levels = compute_camarilla(bar)

    # H3 = 100 + 20 * 1.1/4 = 100 + 5.5 = 105.5
    # L3 = 100 - 20 * 1.1/4 = 100 - 5.5 = 94.5
    # H4 = 100 + 20 * 1.1/2 = 100 + 11 = 111
    # L4 = 100 - 11 = 89
    # P  = (110+90+100)/3 = 100
    assert levels["H3"] == Decimal("105.5")
    assert levels["L3"] == Decimal("94.5")
    assert levels["H4"] == Decimal("111.0")
    assert levels["L4"] == Decimal("89.0")
    assert levels["P"] == Decimal("100")


def test_camarilla_level_ordering():
    """L4 < L3 < L2 < L1 < P < H1 < H2 < H3 < H4 always holds when R > 0."""
    bar = _bar(datetime(2025, 1, 1, tzinfo=UTC), "1000", "1234", "987", "1100")
    levels = compute_camarilla(bar)
    keys = ["L4", "L3", "L2", "L1", "P", "H1", "H2", "H3", "H4"]
    values = [levels[k] for k in keys]
    assert values == sorted(values), f"levels not monotonic: {values}"


def test_camarilla_zero_range_collapses_to_close():
    """If H == L (degenerate flat day), all levels collapse to close."""
    bar = _bar(datetime(2025, 1, 1, tzinfo=UTC), "100", "100", "100", "100")
    levels = compute_camarilla(bar)
    for v in levels.values():
        assert v == Decimal("100")


def test_camarilla_returns_decimal_only():
    """No float leakage. Float in Decimal arithmetic = silent data corruption."""
    bar = _bar(datetime(2025, 1, 1, tzinfo=UTC), "100", "110", "90", "105")
    levels = compute_camarilla(bar)
    for k, v in levels.items():
        assert isinstance(v, Decimal), f"{k} is {type(v).__name__}, expected Decimal"


# ---------- aggregate_to_daily ----------

def test_aggregate_full_day_produces_correct_ohlc():
    bars = _h4_day("2025-01-01", [
        ("100", "105", "98", "103"),    # 00:00
        ("103", "108", "102", "107"),   # 04:00
        ("107", "110", "106", "109"),   # 08:00
        ("109", "112", "104", "105"),   # 12:00  <- contains daily high 112
        ("105", "106", "95", "97"),     # 16:00  <- contains daily low 95
        ("97", "100", "96", "99"),      # 20:00  <- daily close = 99
    ])
    daily = aggregate_to_daily(bars)
    assert len(daily) == 1
    d = daily[0]
    assert d.ts == datetime(2025, 1, 1, tzinfo=UTC)
    assert d.open == Decimal("100")
    assert d.close == Decimal("99")
    assert d.high == Decimal("112")
    assert d.low == Decimal("95")
    assert d.volume == Decimal("6")  # 1 per bar


def test_aggregate_drops_incomplete_day():
    """LOOK-AHEAD GUARD: a day with missing bars must NOT appear in output."""
    full_day = _h4_day("2025-01-01", [("100", "101", "99", "100")] * 6)
    partial_next_day = _h4_day("2025-01-02", [("100", "101", "99", "100")] * 6)[:3]  # only 00, 04, 08
    daily = aggregate_to_daily(full_day + partial_next_day)
    assert len(daily) == 1
    assert daily[0].ts == datetime(2025, 1, 1, tzinfo=UTC)


def test_aggregate_empty_input():
    assert aggregate_to_daily([]) == []


def test_aggregate_requires_sorted():
    full_day = _h4_day("2025-01-01", [("100", "101", "99", "100")] * 6)
    with pytest.raises(ValueError, match="ascending"):
        aggregate_to_daily(list(reversed(full_day)))


def test_aggregate_rejects_non_4h_grid():
    bar = _bar(datetime(2025, 1, 1, 2, tzinfo=UTC), "100", "101", "99", "100")  # 02:00 - off-grid
    with pytest.raises(ValueError, match="4h grid"):
        aggregate_to_daily([bar])


def test_aggregate_rejects_naive_datetime():
    with pytest.raises(ValueError, match="timezone-aware"):
        Bar(ts=datetime(2025, 1, 1),  # naive
            open=Decimal("100"), high=Decimal("101"),
            low=Decimal("99"), close=Decimal("100"), volume=Decimal("1"))


# ---------- Bar validation (added per code review C5/N7) ----------

def test_bar_rejects_zero_low():
    """C5: zero-priced bars cause divide-by-zero downstream; must reject at construction."""
    with pytest.raises(ValueError, match="low must be > 0"):
        Bar(ts=datetime(2025, 1, 1, tzinfo=UTC),
            open=Decimal("0"), high=Decimal("0"), low=Decimal("0"),
            close=Decimal("0"), volume=Decimal("1"))


def test_bar_rejects_negative_low():
    with pytest.raises(ValueError, match="low must be > 0"):
        Bar(ts=datetime(2025, 1, 1, tzinfo=UTC),
            open=Decimal("-1"), high=Decimal("0"), low=Decimal("-2"),
            close=Decimal("-1"), volume=Decimal("1"))


def test_bar_rejects_negative_volume():
    with pytest.raises(ValueError, match="volume must be >= 0"):
        Bar(ts=datetime(2025, 1, 1, tzinfo=UTC),
            open=Decimal("100"), high=Decimal("101"), low=Decimal("99"),
            close=Decimal("100"), volume=Decimal("-1"))


def test_bar_accepts_zero_volume():
    """Zero volume is OK (e.g., illiquid alt during a gap)."""
    bar = Bar(ts=datetime(2025, 1, 1, tzinfo=UTC),
              open=Decimal("100"), high=Decimal("101"), low=Decimal("99"),
              close=Decimal("100"), volume=Decimal("0"))
    assert bar.volume == Decimal("0")


# ---------- look-ahead integration test ----------

def test_no_lookahead_camarilla_for_today_uses_yesterday():
    """End-to-end: aggregation + camarilla must never use today's data for today's levels."""
    day1 = _h4_day("2025-01-01", [("100", "110", "90", "105")] * 6)
    day2_partial = _h4_day("2025-01-02", [("105", "200", "50", "150")] * 6)[:3]  # huge moves today
    all_bars = day1 + day2_partial

    daily = aggregate_to_daily(all_bars)
    assert len(daily) == 1  # only yesterday
    assert daily[0].ts == datetime(2025, 1, 1, tzinfo=UTC)

    # Camarilla for "today" (2025-01-02) is based on yesterday's daily bar
    levels = compute_camarilla(daily[-1])
    # If lookahead bug existed and we accidentally aggregated today's partial data,
    # H would be 200 or close = 150, levels would be massively off.
    # Yesterday: H=110, L=90, C=105 -> H3 = 105 + 20*0.275 = 110.5
    assert levels["H3"] == Decimal("110.5")

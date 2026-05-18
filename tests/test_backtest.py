"""Unit tests for the backtest engine.

Focus: exit logic is correct, look-ahead is impossible, partial fills tracked.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from moritzstrategie.backtest import ExitEvent, Trade, _process_exits, run_backtest, summarize
from moritzstrategie.strategy import Side
from moritzstrategie.types import Bar


UTC = timezone.utc


def _bar(idx: int, o, h, l, c, v="1") -> Bar:
    return Bar(
        ts=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=4 * idx),
        open=Decimal(str(o)), high=Decimal(str(h)),
        low=Decimal(str(l)), close=Decimal(str(c)),
        volume=Decimal(v),
    )


def _open_long_trade() -> Trade:
    return Trade(
        side=Side.LONG,
        entry_idx=10,
        entry_ts=datetime(2025, 1, 1, tzinfo=UTC),
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        tp1_price=Decimal("105"),
        tp2_price=Decimal("110"),
    )


def _open_short_trade() -> Trade:
    return Trade(
        side=Side.SHORT,
        entry_idx=10,
        entry_ts=datetime(2025, 1, 1, tzinfo=UTC),
        entry_price=Decimal("100"),
        stop_price=Decimal("105"),
        tp1_price=Decimal("95"),
        tp2_price=Decimal("90"),
    )


# ---------- Exit triggers ----------

def test_long_stop_hit_when_low_pierces_stop():
    trade = _open_long_trade()
    bar = _bar(11, 99, 100, 94, 98)  # low=94 < stop=95
    _process_exits(trade, bar, 11, time_stop_bars=12)
    assert len(trade.exits) == 1
    assert trade.exits[0].reason == "stop"
    assert trade.exits[0].price == Decimal("95")
    assert trade.closed


def test_long_tp1_then_tp2_in_same_bar():
    """Both targets in one bar: tp1 first, then tp2 (trade closes)."""
    trade = _open_long_trade()
    bar = _bar(11, 100, 111, 99, 110)  # high=111 covers both 105 and 110
    _process_exits(trade, bar, 11, time_stop_bars=12)
    assert [e.reason for e in trade.exits] == ["tp1", "tp2"]
    assert trade.closed


def test_long_tp1_only_first_bar_then_tp2_later():
    trade = _open_long_trade()
    # Bar 11: tp1 hit, tp2 not yet
    _process_exits(trade, _bar(11, 100, 105.5, 99, 105), 11, 12)
    assert [e.reason for e in trade.exits] == ["tp1"]
    assert not trade.closed
    # Bar 12: tp2 hit
    _process_exits(trade, _bar(12, 105, 111, 104, 110), 12, 12)
    assert [e.reason for e in trade.exits] == ["tp1", "tp2"]
    assert trade.closed


def test_long_stop_priority_over_tp_when_both_in_range():
    """Conservative ordering: if bar range covers both stop AND tp, stop fills first."""
    trade = _open_long_trade()
    # Range 94..111 covers stop=95 AND tp2=110. Stop must win.
    bar = _bar(11, 100, 111, 94, 100)
    _process_exits(trade, bar, 11, 12)
    assert trade.exits[0].reason == "stop"
    assert trade.closed


def test_short_stop_hit():
    trade = _open_short_trade()
    bar = _bar(11, 100, 106, 99, 105)  # high=106 > stop=105
    _process_exits(trade, bar, 11, 12)
    assert trade.exits[0].reason == "stop"


def test_short_tp_progression():
    trade = _open_short_trade()
    _process_exits(trade, _bar(11, 100, 101, 94.5, 95), 11, 12)
    assert [e.reason for e in trade.exits] == ["tp1"]
    _process_exits(trade, _bar(12, 95, 96, 89, 90), 12, 12)
    assert [e.reason for e in trade.exits] == ["tp1", "tp2"]


def test_time_stop_triggers_at_threshold():
    trade = _open_long_trade()  # entry_idx=10
    # Quiet bars that don't trigger anything
    for i in range(11, 22):
        _process_exits(trade, _bar(i, 100, 101, 99, 100), i, 12)
    assert not trade.closed
    # Bar 22 = entry_idx + 12 -> time-stop fires
    _process_exits(trade, _bar(22, 100, 101, 99, 100), 22, 12)
    assert trade.exits[-1].reason == "time_stop"
    assert trade.closed


def test_no_exit_on_entry_bar_itself():
    """The bar where entry fires must not also trigger exit (conservative)."""
    trade = _open_long_trade()  # entry_idx=10
    bar = _bar(10, 100, 200, 50, 100)  # extreme range
    _process_exits(trade, bar, 10, 12)
    assert trade.exits == []


# ---------- PnL ----------

def test_long_pnl_50_50_split():
    trade = _open_long_trade()
    _process_exits(trade, _bar(11, 100, 105.5, 99, 105), 11, 12)
    _process_exits(trade, _bar(12, 105, 111, 104, 110), 12, 12)
    # 50% @ +5%, 50% @ +10% -> 7.5%
    assert trade.pnl_pct() == Decimal("0.075")


def test_long_pnl_full_loss_at_stop():
    trade = _open_long_trade()
    _process_exits(trade, _bar(11, 99, 100, 94, 95), 11, 12)
    # Full position at -5%
    assert trade.pnl_pct() == Decimal("-0.05")


def test_short_pnl_winner():
    trade = _open_short_trade()
    _process_exits(trade, _bar(11, 100, 101, 94.5, 95), 11, 12)
    _process_exits(trade, _bar(12, 95, 96, 89, 90), 12, 12)
    # Short from 100: tp1=95 (+5%), tp2=90 (+10%) -> 7.5%
    assert trade.pnl_pct() == Decimal("0.075")


# ---------- run_backtest end-to-end ----------

def test_run_backtest_empty_input():
    assert run_backtest([]) == []


def test_run_backtest_flat_data_no_trades():
    """Flat data -> RSI flat at 50 -> no oversold/overbought -> no trades."""
    bars = [_bar(i, 100, 101, 99, 100) for i in range(200)]
    trades = run_backtest(bars)
    assert trades == []


def test_summarize_empty():
    s = summarize([])
    assert s["trades"] == 0


def test_long_pnl_tp1_then_stop_50_50_split():
    """TP1 hits, then on a later bar stop fires on the remaining 50%.

    Verifies H6 from code review: implicit 50/50 accounting handles TP1→Stop correctly.
    """
    trade = _open_long_trade()
    # Bar 11: TP1 hits
    _process_exits(trade, _bar(11, 100, 105.5, 99, 105), 11, 12)
    assert [e.reason for e in trade.exits] == ["tp1"]
    assert not trade.closed
    # Bar 12: stop hits
    _process_exits(trade, _bar(12, 100, 102, 94, 96), 12, 12)
    assert [e.reason for e in trade.exits] == ["tp1", "stop"]
    assert trade.closed
    # 50% @ +5%, 50% @ -5% -> net 0
    assert trade.pnl_pct() == Decimal("0")


def test_short_pnl_tp1_then_stop_correct_accounting():
    trade = _open_short_trade()  # entry 100, stop 105, tp1 95, tp2 90
    _process_exits(trade, _bar(11, 100, 101, 94.5, 95), 11, 12)
    assert [e.reason for e in trade.exits] == ["tp1"]
    _process_exits(trade, _bar(12, 96, 106, 95, 105), 12, 12)
    assert [e.reason for e in trade.exits] == ["tp1", "stop"]
    # Short from 100: 50% @ tp1=95 (+5%), 50% @ stop=105 (-5%) -> net 0
    assert trade.pnl_pct() == Decimal("0")


def test_friction_applied_to_long_winner_reduces_net_pnl():
    """A trade that goes TP1+TP2: gross=7.5%, friction adds fee+funding+slippage cost."""
    from moritzstrategie.friction import default_bitget_friction
    friction = default_bitget_friction()
    trade = _open_long_trade()
    # Simulate engine charging entry fee + slippage on entry would have been pre-adjusted;
    # here we directly set friction_pct to entry fee for unit isolation.
    trade.friction_pct = friction.fee_cost(Decimal("1"), is_taker=True)  # 6 bps
    _process_exits(trade, _bar(11, 100, 105.5, 99, 105), 11, 12, friction=friction)
    _process_exits(trade, _bar(12, 105, 111, 104, 110), 12, 12, friction=friction)
    # Gross PnL (50/50): 0.5*5% + 0.5*10% = 7.5%
    # But exit prices are now slippage-adjusted (cheaper for long exit)
    # Net = gross - friction_pct (entry fee + 2 exit fees + slippage already in prices)
    assert trade.net_pnl_pct() < trade.pnl_pct()
    assert trade.friction_pct > Decimal("0")


def test_friction_none_keeps_pnl_unchanged():
    """Without friction, net_pnl_pct == pnl_pct (no costs accrued)."""
    trade = _open_long_trade()
    _process_exits(trade, _bar(11, 100, 105.5, 99, 105), 11, 12, friction=None)
    _process_exits(trade, _bar(12, 105, 111, 104, 110), 12, 12, friction=None)
    assert trade.friction_pct == Decimal("0")
    assert trade.net_pnl_pct() == trade.pnl_pct()


def test_friction_exit_fee_split_on_tp1_then_stop():
    """TP1 charges 0.5 fee, stop on remaining 50% charges another 0.5 fee."""
    from moritzstrategie.friction import default_bitget_friction
    friction = default_bitget_friction()
    trade = _open_long_trade()
    _process_exits(trade, _bar(11, 100, 105.5, 99, 105), 11, 12, friction=friction)
    fee_after_tp1 = trade.friction_pct
    _process_exits(trade, _bar(12, 100, 102, 94, 96), 12, 12, friction=friction)
    fee_after_stop = trade.friction_pct
    # Each leg = 0.5 * 6bps = 3bps. Two legs = 6bps total.
    assert fee_after_tp1 == Decimal("0.5") * Decimal("0.0006")
    assert fee_after_stop == Decimal("0.0006")


def test_summarize_basic_stats():
    # Construct two synthetic closed trades
    t1 = _open_long_trade()
    t1.exits = [
        ExitEvent("tp1", Decimal("105"), 11, datetime(2025, 1, 1, tzinfo=UTC)),
        ExitEvent("tp2", Decimal("110"), 12, datetime(2025, 1, 1, tzinfo=UTC)),
    ]
    t2 = _open_long_trade()
    t2.exits = [ExitEvent("stop", Decimal("95"), 11, datetime(2025, 1, 1, tzinfo=UTC))]

    s = summarize([t1, t2])
    assert s["trades"] == 2
    assert s["winners"] == 1
    assert s["losers"] == 1
    assert s["win_rate"] == Decimal("0.5")

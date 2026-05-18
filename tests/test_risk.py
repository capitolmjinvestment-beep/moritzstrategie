"""Unit tests for risk management module."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from moritzstrategie.risk import (
    PortfolioState,
    RiskManager,
    RiskParams,
    position_size_from_risk,
)


UTC = timezone.utc


# ---------- position_size_from_risk ----------

def test_position_size_basic_calculation():
    """MASTERPLAN example: equity 1000, risk 1.5%, entry 60000, stop 58800
    -> risk_amount = 15, stop_distance = 1200, qty = 0.0125."""
    qty = position_size_from_risk(
        equity=Decimal("1000"), risk_pct=Decimal("0.015"),
        entry_price=Decimal("60000"), stop_price=Decimal("58800"),
    )
    assert qty == Decimal("0.0125")


def test_position_size_short_stop_above_entry():
    """For shorts, stop > entry. Math is symmetric (abs)."""
    qty = position_size_from_risk(
        equity=Decimal("1000"), risk_pct=Decimal("0.015"),
        entry_price=Decimal("60000"), stop_price=Decimal("61200"),
    )
    assert qty == Decimal("0.0125")


def test_position_size_rejects_zero_equity():
    with pytest.raises(ValueError, match="equity must be > 0"):
        position_size_from_risk(Decimal("0"), Decimal("0.015"), Decimal("100"), Decimal("90"))


def test_position_size_rejects_negative_equity():
    with pytest.raises(ValueError, match="equity must be > 0"):
        position_size_from_risk(Decimal("-100"), Decimal("0.015"), Decimal("100"), Decimal("90"))


def test_position_size_rejects_invalid_risk_pct():
    with pytest.raises(ValueError, match="risk_pct must be in"):
        position_size_from_risk(Decimal("1000"), Decimal("0"), Decimal("100"), Decimal("90"))
    with pytest.raises(ValueError, match="risk_pct must be in"):
        position_size_from_risk(Decimal("1000"), Decimal("1.5"), Decimal("100"), Decimal("90"))


def test_position_size_rejects_entry_equals_stop():
    with pytest.raises(ValueError, match="entry_price and stop_price are equal"):
        position_size_from_risk(Decimal("1000"), Decimal("0.015"), Decimal("100"), Decimal("100"))


def test_position_size_rejects_zero_price():
    with pytest.raises(ValueError, match="prices must be > 0"):
        position_size_from_risk(Decimal("1000"), Decimal("0.015"), Decimal("0"), Decimal("90"))


# ---------- PortfolioState ----------

def test_portfolio_state_fresh():
    s = PortfolioState.fresh(Decimal("1000"))
    assert s.initial_equity == Decimal("1000")
    assert s.current_equity == Decimal("1000")
    assert s.today_pnl == Decimal("0")
    assert s.total_open == 0


def test_portfolio_state_realize_pnl_updates_equity_and_today():
    s = PortfolioState.fresh(Decimal("1000"))
    s.realize_pnl(Decimal("10"), datetime(2025, 1, 1, 12, tzinfo=UTC))
    assert s.current_equity == Decimal("1010")
    assert s.today_pnl == Decimal("10")


def test_portfolio_state_today_pnl_resets_on_new_day():
    s = PortfolioState.fresh(Decimal("1000"))
    s.realize_pnl(Decimal("-50"), datetime(2025, 1, 1, 23, tzinfo=UTC))
    assert s.today_pnl == Decimal("-50")
    # Next day
    s.realize_pnl(Decimal("20"), datetime(2025, 1, 2, 1, tzinfo=UTC))
    assert s.today_pnl == Decimal("20")  # reset
    assert s.current_equity == Decimal("970")  # cumulative


def test_portfolio_state_rejects_naive_datetime():
    s = PortfolioState.fresh(Decimal("1000"))
    with pytest.raises(ValueError, match="timezone-aware"):
        s.realize_pnl(Decimal("10"), datetime(2025, 1, 1))


def test_portfolio_state_position_tracking():
    s = PortfolioState.fresh(Decimal("1000"))
    s.open_position("BTC")
    s.open_position("ETH")
    assert s.total_open == 2
    s.close_position("BTC")
    assert s.total_open == 1
    assert "BTC" not in s.open_positions


# ---------- RiskManager kill switches ----------

def test_risk_manager_allows_first_trade():
    rm = RiskManager(PortfolioState.fresh(Decimal("1000")))
    d = rm.check_entry_allowed("BTC", Decimal("60000"), Decimal("58800"))
    assert d.allowed
    assert d.position_qty == Decimal("0.0125")


def test_risk_manager_daily_kill_blocks_at_minus_10pct():
    s = PortfolioState.fresh(Decimal("1000"))
    s.realize_pnl(Decimal("-100"), datetime(2025, 1, 1, 12, tzinfo=UTC))  # -10% today
    rm = RiskManager(s)
    d = rm.check_entry_allowed("BTC", Decimal("60000"), Decimal("58800"))
    assert not d.allowed
    assert "daily_kill" in d.reason


def test_risk_manager_daily_kill_does_not_trigger_at_minus_9pct():
    s = PortfolioState.fresh(Decimal("1000"))
    s.realize_pnl(Decimal("-90"), datetime(2025, 1, 1, 12, tzinfo=UTC))  # -9% today
    rm = RiskManager(s)
    d = rm.check_entry_allowed("BTC", Decimal("60000"), Decimal("58800"))
    assert d.allowed


def test_risk_manager_aggregate_kill_blocks_at_minus_20pct():
    s = PortfolioState.fresh(Decimal("1000"))
    # Spread the loss across two days so daily kill doesn't trigger
    s.realize_pnl(Decimal("-100"), datetime(2025, 1, 1, 12, tzinfo=UTC))
    s.realize_pnl(Decimal("-100"), datetime(2025, 1, 2, 12, tzinfo=UTC))
    rm = RiskManager(s)
    d = rm.check_entry_allowed("BTC", Decimal("60000"), Decimal("58800"))
    assert not d.allowed
    assert "aggregate_kill" in d.reason


def test_risk_manager_max_per_symbol():
    s = PortfolioState.fresh(Decimal("1000"))
    s.open_position("BTC")
    rm = RiskManager(s)
    d = rm.check_entry_allowed("BTC", Decimal("60000"), Decimal("58800"))
    assert not d.allowed
    assert "max_per_symbol" in d.reason


def test_risk_manager_max_total_positions():
    s = PortfolioState.fresh(Decimal("1000"))
    s.open_position("BTC")
    s.open_position("ETH")
    rm = RiskManager(s)
    d = rm.check_entry_allowed("SOL", Decimal("100"), Decimal("95"))
    assert not d.allowed
    assert "max_total_positions" in d.reason


def test_risk_manager_busted_account():
    s = PortfolioState.fresh(Decimal("1000"))
    s.current_equity = Decimal("0")
    rm = RiskManager(s)
    d = rm.check_entry_allowed("BTC", Decimal("60000"), Decimal("58800"))
    assert not d.allowed
    assert d.reason == "account_busted"


def test_risk_manager_sizing_error_invalid_entry():
    rm = RiskManager(PortfolioState.fresh(Decimal("1000")))
    d = rm.check_entry_allowed("BTC", Decimal("60000"), Decimal("60000"))
    assert not d.allowed
    assert "sizing_error" in d.reason


def test_risk_manager_custom_risk_params():
    """Allow tuning per-strategy: e.g. test with 3% risk to see allowed sizes."""
    rm = RiskManager(
        PortfolioState.fresh(Decimal("1000")),
        RiskParams(risk_per_trade_pct=Decimal("0.03")),
    )
    d = rm.check_entry_allowed("BTC", Decimal("60000"), Decimal("58800"))
    assert d.allowed
    # risk = 30, distance = 1200, qty = 0.025
    assert d.position_qty == Decimal("0.025")

"""H4 Camarilla Reversal indicator library.

Public API (use these in downstream consumers):

  # Types
  Bar, Pattern, PatternResult, Side

  # Indicators (pure)
  aggregate_to_daily, compute_camarilla, compute_rsi, compute_atr
  detect_double_bottom, detect_double_top

  # Strategy (pure)
  EntryParams, EntrySignal, evaluate_entry

  # Friction
  FrictionModel, FeeSchedule, FundingSchedule, SlippageModel
  BitgetTakerFee, PeriodicFunding, ConstantSlippage, VolatilitySlippage
  default_bitget_friction

  # Risk
  PortfolioState, RiskParams, RiskManager, EntryDecision
  position_size_from_risk

  # Backtest layers (composable)
  Trade, ExitEvent, run_backtest, summarize
  PortfolioTrade, PortfolioResult, run_portfolio_backtest

  # Validation
  WalkForwardWindow, WalkForwardReport, walk_forward, BARS_PER_MONTH

  # Precision
  quantize_price, quantize_camarilla, tick_for, BITGET_TICK_SIZES

Internal helpers (prefixed _) are NOT part of the public API.
"""

from .aggregation import aggregate_to_daily
from .atr import compute_atr
from .backtest import ExitEvent, Trade, run_backtest, summarize
from .camarilla import compute_camarilla
from .friction import (
    BitgetTakerFee,
    ConstantSlippage,
    FeeSchedule,
    FrictionModel,
    FundingSchedule,
    PeriodicFunding,
    SlippageModel,
    VolatilitySlippage,
    default_bitget_friction,
)
from .patterns import detect_double_bottom, detect_double_top
from .portfolio_backtest import (
    PortfolioResult,
    PortfolioTrade,
    run_portfolio_backtest,
)
from .precision import (
    BITGET_TICK_SIZES,
    quantize_camarilla,
    quantize_price,
    tick_for,
)
from .risk import (
    EntryDecision,
    PortfolioState,
    RiskManager,
    RiskParams,
    position_size_from_risk,
)
from .rsi import compute_rsi
from .strategy import EntryParams, EntrySignal, Side, evaluate_entry
from .types import Bar, Pattern, PatternResult
from .walk_forward import (
    BARS_PER_MONTH,
    WalkForwardReport,
    WalkForwardWindow,
    walk_forward,
)

__all__ = [
    # Types
    "Bar", "Pattern", "PatternResult", "Side",
    # Indicators
    "aggregate_to_daily", "compute_camarilla", "compute_rsi", "compute_atr",
    "detect_double_bottom", "detect_double_top",
    # Strategy
    "EntryParams", "EntrySignal", "evaluate_entry",
    # Friction
    "FrictionModel", "FeeSchedule", "FundingSchedule", "SlippageModel",
    "BitgetTakerFee", "PeriodicFunding",
    "ConstantSlippage", "VolatilitySlippage",
    "default_bitget_friction",
    # Risk
    "PortfolioState", "RiskParams", "RiskManager", "EntryDecision",
    "position_size_from_risk",
    # Backtest
    "Trade", "ExitEvent", "run_backtest", "summarize",
    "PortfolioTrade", "PortfolioResult", "run_portfolio_backtest",
    # Walk-forward
    "WalkForwardWindow", "WalkForwardReport", "walk_forward", "BARS_PER_MONTH",
    # Precision
    "quantize_price", "quantize_camarilla", "tick_for", "BITGET_TICK_SIZES",
]

"""Tick-size quantization for price comparisons.

Resolves REVIEW.md H1: Decimal division (e.g., Camarilla P = (H+L+C)/3) produces
non-terminating decimals that don't align with exchange tick sizes. When you
compare `bar.close <= L3` and L3 has 28 decimal places, sporadic false-equality
mismatches happen if `bar.close` was loaded with finite precision (e.g., from
parquet, which drops trailing zeros).

Bitget tick sizes (verify against current API before live):
  BTCUSDT-PERP: 0.1
  ETHUSDT-PERP: 0.01
  SOLUSDT-PERP: 0.001
  BNBUSDT-PERP: 0.001
  ARBUSDT-PERP: 0.0001
  ...

Standard rule: round HALF_UP. The choice of rounding mode is largely cosmetic
for backtest purposes (any consistent rule avoids the comparison-mismatch bug),
but HALF_UP matches what most charting tools display.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# Hardcoded mapping for known symbols. Replace with live API call when integrated.
# Source: Bitget USDT-Perp contract specs (2025). Re-verify before live.
BITGET_TICK_SIZES: dict[str, Decimal] = {
    "BTCUSDT": Decimal("0.1"),
    "ETHUSDT": Decimal("0.01"),
    "SOLUSDT": Decimal("0.001"),
    "BNBUSDT": Decimal("0.001"),
    "XRPUSDT": Decimal("0.0001"),
    "ADAUSDT": Decimal("0.0001"),
    "DOGEUSDT": Decimal("0.00001"),
    "AVAXUSDT": Decimal("0.001"),
}


def quantize_price(price: Decimal, tick: Decimal) -> Decimal:
    """Round `price` to the nearest multiple of `tick`.

    Args:
        price: Raw Decimal price (may have unbounded precision from division).
        tick: Exchange tick size, e.g. Decimal("0.1") for BTC.

    Returns:
        Price rounded to the tick grid.

    Examples:
        quantize_price(Decimal("60123.456789"), Decimal("0.1")) -> Decimal("60123.5")
        quantize_price(Decimal("60000.04"), Decimal("0.1")) -> Decimal("60000.0")
        quantize_price(Decimal("60000.05"), Decimal("0.1")) -> Decimal("60000.1")  # HALF_UP
    """
    if tick <= 0:
        raise ValueError(f"tick must be > 0, got {tick}")
    if price < 0:
        raise ValueError(f"price must be >= 0, got {price}")
    return (price / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick


def quantize_camarilla(
    levels: dict[str, Decimal], tick: Decimal
) -> dict[str, Decimal]:
    """Apply tick-quantization to every level in a Camarilla dict.

    Use this in production before passing levels to `evaluate_entry` to ensure
    price comparisons are deterministic against bar prices loaded from the feed.
    """
    return {key: quantize_price(value, tick) for key, value in levels.items()}


def tick_for(symbol: str) -> Decimal:
    """Look up tick size for a known symbol. Raises if symbol unknown.

    For production: replace with a call to BitgetClient.get_contract_spec(symbol).
    """
    if symbol not in BITGET_TICK_SIZES:
        raise KeyError(
            f"Unknown symbol {symbol!r}. Add to BITGET_TICK_SIZES or fetch via API."
        )
    return BITGET_TICK_SIZES[symbol]

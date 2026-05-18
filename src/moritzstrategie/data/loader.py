"""On-disk cache + lazy fetch for historical bars.

Caching strategy:
  - Per (symbol, granularity), bars are stored in a single CSV file.
  - CSV format: ts_iso,open,high,low,close,volume
  - Filename: data/{symbol}_{granularity}.csv
  - On read: load all bars, return as list[Bar].
  - On write: append or rewrite the whole file (small enough; ~6k bars / year).

Why CSV and not parquet:
  - Zero external dependency (parquet needs pyarrow or fastparquet).
  - Human-readable: you can open in any editor / Excel to sanity check.
  - Small for 4h bars: 1 year × 3 symbols ≈ 6500 rows × ~80 bytes = 0.5 MB. Trivial.

For 1m bars or multi-year datasets, switch to parquet. For 4h × 3 symbols × 3 years,
CSV is perfectly fine.

Public API:
  - load(symbol, granularity, data_dir) -> list[Bar]
  - save(symbol, granularity, bars, data_dir) -> None
  - fetch_or_load(symbol, granularity, start, end, client, data_dir) -> list[Bar]
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional, Sequence

from ..types import Bar
from .bitget_rest import BitgetClient
from .integrity import assert_clean


_HEADER = ["ts_iso", "open", "high", "low", "close", "volume"]


def _csv_path(symbol: str, granularity: str, data_dir: Path) -> Path:
    safe_sym = symbol.replace("/", "_").upper()
    safe_gran = granularity.replace(" ", "")
    return data_dir / f"{safe_sym}_{safe_gran}.csv"


def load(
    symbol: str,
    granularity: str = "4H",
    data_dir: Path = Path("data"),
) -> list[Bar]:
    """Load all cached bars for (symbol, granularity).

    Returns empty list if cache file doesn't exist.
    Bars are validated by Bar.__post_init__ on parse.
    """
    path = _csv_path(symbol, granularity, data_dir)
    if not path.exists():
        return []
    bars: list[Bar] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != _HEADER:
            raise ValueError(
                f"unexpected CSV header in {path}: {reader.fieldnames}, "
                f"expected {_HEADER}"
            )
        for row in reader:
            ts = datetime.fromisoformat(row["ts_iso"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            bars.append(Bar(
                ts=ts,
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                volume=Decimal(row["volume"]),
            ))
    bars.sort(key=lambda b: b.ts)
    return bars


def save(
    symbol: str,
    granularity: str,
    bars: Sequence[Bar],
    data_dir: Path = Path("data"),
) -> Path:
    """Atomically write bars to cache file. Returns the path written."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = _csv_path(symbol, granularity, data_dir)
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_HEADER)
        for b in bars:
            writer.writerow([
                b.ts.isoformat(),
                str(b.open), str(b.high), str(b.low),
                str(b.close), str(b.volume),
            ])
    tmp.replace(path)  # atomic on POSIX
    return path


def fetch_or_load(
    symbol: str,
    granularity: str,
    start_ts: datetime,
    end_ts: datetime,
    client: Optional[BitgetClient] = None,
    data_dir: Path = Path("data"),
    validate: bool = True,
) -> list[Bar]:
    """Load cached bars; fetch missing ranges from API if needed.

    Strategy:
      1. Load cache.
      2. If cache covers [start_ts, end_ts], slice and return.
      3. Otherwise, fetch full range from API, MERGE with cache (dedup by ts),
         re-save, slice, return.

    Args:
        client: BitgetClient. If None and fetch is needed, raises RuntimeError.
        validate: If True, run integrity.assert_clean() on returned bars.

    Returns:
        Bars in [start_ts, end_ts] inclusive, ascending.
    """
    cached = load(symbol, granularity, data_dir)
    cached_in_range = [b for b in cached if start_ts <= b.ts <= end_ts]

    # Quick check: do we have an unbroken cache for the requested range?
    if cached_in_range:
        first_cached = cached_in_range[0].ts
        last_cached = cached_in_range[-1].ts
        cache_covers = (first_cached <= start_ts + _period(granularity)
                        and last_cached >= end_ts - _period(granularity))
        if cache_covers:
            if validate:
                assert_clean(cached_in_range, granularity)
            return cached_in_range

    # Need to fetch
    if client is None:
        raise RuntimeError(
            f"Cache miss for {symbol} {granularity} {start_ts}..{end_ts}; "
            f"pass a BitgetClient to fetch from API."
        )
    fetched = client.get_klines_range(
        symbol=symbol,
        granularity=granularity,
        start_ms=int(start_ts.timestamp() * 1000),
        end_ms=int(end_ts.timestamp() * 1000),
    )

    # Merge cached + fetched, dedupe by ts (fetched wins for overlaps)
    merged: dict[datetime, Bar] = {b.ts: b for b in cached}
    for b in fetched:
        merged[b.ts] = b
    all_bars = sorted(merged.values(), key=lambda b: b.ts)

    # Persist
    save(symbol, granularity, all_bars, data_dir)

    result = [b for b in all_bars if start_ts <= b.ts <= end_ts]
    if validate:
        assert_clean(result, granularity)
    return result


def _period(granularity: str):
    """Return timedelta for one bar."""
    from datetime import timedelta
    from .integrity import GRANULARITY_MINUTES
    return timedelta(minutes=GRANULARITY_MINUTES[granularity])

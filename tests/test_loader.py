"""Tests for the CSV cache loader."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from moritzstrategie.data.loader import load, save, _csv_path
from moritzstrategie.types import Bar


UTC = timezone.utc


def _bar(idx: int) -> Bar:
    return Bar(
        ts=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=4 * idx),
        open=Decimal("100"), high=Decimal("101"),
        low=Decimal("99"), close=Decimal("100"), volume=Decimal("1"),
    )


def test_load_missing_file_returns_empty(tmp_path: Path):
    assert load("BTCUSDT", "4H", data_dir=tmp_path) == []


def test_save_then_load_roundtrip(tmp_path: Path):
    original = [_bar(i) for i in range(5)]
    save("BTCUSDT", "4H", original, data_dir=tmp_path)
    loaded = load("BTCUSDT", "4H", data_dir=tmp_path)
    assert len(loaded) == 5
    for orig, l in zip(original, loaded):
        assert orig.ts == l.ts
        assert orig.open == l.open
        assert orig.high == l.high
        assert orig.low == l.low
        assert orig.close == l.close
        assert orig.volume == l.volume


def test_save_creates_data_dir(tmp_path: Path):
    nested = tmp_path / "nested" / "subdir"
    save("BTCUSDT", "4H", [_bar(0)], data_dir=nested)
    assert (nested / "BTCUSDT_4H.csv").exists()


def test_load_sorts_bars_ascending(tmp_path: Path):
    """Even if cache file is corrupted with out-of-order rows, load() sorts."""
    bars = [_bar(0), _bar(1), _bar(2)]
    save("BTCUSDT", "4H", bars, data_dir=tmp_path)
    # Manually rewrite with reverse order
    path = _csv_path("BTCUSDT", "4H", tmp_path)
    lines = path.read_text().splitlines()
    rewritten = [lines[0]] + lines[1:][::-1]
    path.write_text("\n".join(rewritten) + "\n")
    loaded = load("BTCUSDT", "4H", data_dir=tmp_path)
    assert [b.ts for b in loaded] == [b.ts for b in bars]


def test_csv_path_normalizes_symbol(tmp_path: Path):
    path = _csv_path("btcusdt", "4H", tmp_path)
    assert path.name == "BTCUSDT_4H.csv"


def test_load_rejects_unknown_header(tmp_path: Path):
    path = _csv_path("BTCUSDT", "4H", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("wrong,header,row\n1,2,3\n")
    with pytest.raises(ValueError, match="unexpected CSV header"):
        load("BTCUSDT", "4H", data_dir=tmp_path)

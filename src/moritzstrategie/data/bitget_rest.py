"""Bitget v2 USDT-Perpetual REST client (read-only).

Stdlib-only HTTP (urllib) — no external dependencies. Sufficient for batch
historical pulls. For high-frequency live data use a proper WebSocket client.

Public endpoints (klines, ticker, contract specs) need no auth.
Private endpoints (account info, positions) sign with HMAC-SHA256 per
Bitget v2 docs: https://www.bitget.com/api-doc/common/signature

Signing recipe:
    prehash = timestamp_ms + method.upper() + request_path + body
    signature = base64(hmac_sha256(api_secret, prehash))

Headers for private requests:
    ACCESS-KEY:        api_key
    ACCESS-SIGN:       signature
    ACCESS-TIMESTAMP:  timestamp_ms
    ACCESS-PASSPHRASE: passphrase
    Content-Type:      application/json
    locale:            en-US (optional)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from ..types import Bar


# Bitget v2 granularity codes per product type. USDT-FUTURES supports these.
VALID_GRANULARITIES = {"1m", "3m", "5m", "15m", "30m", "1H", "4H", "6H", "12H", "1D", "1W", "1M"}


def _load_dotenv(path: Path) -> dict[str, str]:
    """Tiny .env parser. No external dependency."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip()
    return env


@dataclass(frozen=True)
class BitgetCredentials:
    api_key: str
    api_secret: str
    passphrase: str
    base_url: str = "https://api.bitget.com"

    @classmethod
    def from_env(cls, env_path: Optional[Path] = None) -> "BitgetCredentials":
        """Load from .env file (and override with os.environ if set)."""
        if env_path is None:
            # repo_root/.env (this file is at src/moritzstrategie/data/bitget_rest.py)
            env_path = Path(__file__).resolve().parents[3] / ".env"
        env = _load_dotenv(env_path)
        for k in ("BITGET_API_KEY", "BITGET_API_SECRET",
                  "BITGET_API_PASSPHRASE", "BITGET_BASE_URL"):
            if k in os.environ:
                env[k] = os.environ[k]
        required = ("BITGET_API_KEY", "BITGET_API_SECRET", "BITGET_API_PASSPHRASE")
        missing = [k for k in required if not env.get(k)]
        if missing:
            raise RuntimeError(
                f"Missing env vars: {missing}. Copy .env.example to .env and fill in."
            )
        return cls(
            api_key=env["BITGET_API_KEY"],
            api_secret=env["BITGET_API_SECRET"],
            passphrase=env["BITGET_API_PASSPHRASE"],
            base_url=env.get("BITGET_BASE_URL", cls.base_url),
        )


class BitgetClient:
    """Read-only REST client for Bitget v2 USDT-Perpetual market data."""

    def __init__(self, creds: BitgetCredentials, timeout_s: int = 30):
        self.creds = creds
        self.timeout_s = timeout_s

    @classmethod
    def from_env(cls, env_path: Optional[Path] = None) -> "BitgetClient":
        return cls(BitgetCredentials.from_env(env_path))

    # ---------- Public endpoints (no auth) ----------

    def get_klines(
        self,
        symbol: str,
        granularity: str = "4H",
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        limit: int = 1000,
        use_history_endpoint: bool = True,
    ) -> list[Bar]:
        """Fetch up to `limit` klines for a USDT-perpetual symbol.

        Args:
            symbol: e.g. "BTCUSDT" (Bitget format, no separator).
            granularity: one of VALID_GRANULARITIES. Default "4H".
            start_ms: optional inclusive lower bound (UTC ms timestamp).
            end_ms: optional inclusive upper bound (UTC ms timestamp).
            limit: max 1000 per Bitget v2 docs.
            use_history_endpoint: True (default) uses `/history-candles` which
                covers 2+ years of data but has ~4h lag on the most recent bar.
                False uses `/candles` which has ~6 months of data but is real-time.

        Returns:
            List of Bar in ascending time order.
        """
        if granularity not in VALID_GRANULARITIES:
            raise ValueError(
                f"granularity {granularity!r} not in {sorted(VALID_GRANULARITIES)}"
            )
        # Bitget v2: candles supports limit<=1000, history-candles only limit<=200
        max_limit = 200 if use_history_endpoint else 1000
        if limit < 1 or limit > max_limit:
            raise ValueError(
                f"limit must be in [1, {max_limit}] for "
                f"{'history-candles' if use_history_endpoint else 'candles'}, got {limit}"
            )

        params: dict[str, str] = {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "granularity": granularity,
            "limit": str(limit),
        }
        if start_ms is not None:
            params["startTime"] = str(start_ms)
        if end_ms is not None:
            params["endTime"] = str(end_ms)

        path = ("/api/v2/mix/market/history-candles"
                if use_history_endpoint
                else "/api/v2/mix/market/candles")
        url = self.creds.base_url + path + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=self.timeout_s) as r:
            body = r.read().decode("utf-8")
        data = json.loads(body)
        if data.get("code") != "00000":
            raise RuntimeError(f"Bitget API error: {data}")

        bars: list[Bar] = []
        for row in data.get("data", []):
            # v2 kline row: [ts_ms, open, high, low, close, base_vol, quote_vol]
            ts_ms = int(row[0])
            bars.append(Bar(
                ts=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[5])),
            ))
        bars.sort(key=lambda b: b.ts)
        return bars

    # ---------- Private endpoints (auth required) ----------

    def _sign(self, timestamp_ms: str, method: str, request_path: str, body: str = "") -> str:
        prehash = timestamp_ms + method.upper() + request_path + body
        digest = hmac.new(
            self.creds.api_secret.encode("utf-8"),
            prehash.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _authed_get(self, path: str, query: Optional[dict[str, str]] = None) -> dict:
        full_path = path
        if query:
            full_path = path + "?" + urllib.parse.urlencode(query)
        ts = str(int(time.time() * 1000))
        sig = self._sign(ts, "GET", full_path)
        req = urllib.request.Request(self.creds.base_url + full_path)
        req.add_header("ACCESS-KEY", self.creds.api_key)
        req.add_header("ACCESS-SIGN", sig)
        req.add_header("ACCESS-TIMESTAMP", ts)
        req.add_header("ACCESS-PASSPHRASE", self.creds.passphrase)
        req.add_header("Content-Type", "application/json")
        req.add_header("locale", "en-US")
        with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))

    def get_account_info(self) -> dict:
        """Returns the USDT-FUTURES account list. Used as auth-sanity check."""
        return self._authed_get(
            "/api/v2/mix/account/accounts",
            query={"productType": "USDT-FUTURES"},
        )

    # ---------- Convenience: paged historical pull ----------

    # Bitget v2 single-call cap is 90 days. We chunk smaller to fit limit=200
    # of history-candles. For 4h bars: 200 bars × 4h = ~33 days per chunk.
    _MAX_CHUNK_MS = 30 * 24 * 60 * 60 * 1000  # 30-day chunks (conservative)

    def get_klines_range(
        self,
        symbol: str,
        granularity: str,
        start_ms: int,
        end_ms: int,
        page_size: int = 200,
        use_history_endpoint: bool = True,
    ) -> list[Bar]:
        """Pull all klines in [start_ms, end_ms], chunking around Bitget's 90-day cap.

        Returns ascending-time list, deduplicated by timestamp.
        """
        if end_ms <= start_ms:
            raise ValueError(f"end_ms ({end_ms}) must be > start_ms ({start_ms})")
        out: dict[datetime, Bar] = {}
        chunk_start = start_ms
        # Safety: cap iterations so a bug can't infinite-loop
        for _ in range(200):
            if chunk_start >= end_ms:
                break
            chunk_end = min(chunk_start + self._MAX_CHUNK_MS, end_ms)
            page = self.get_klines(
                symbol=symbol,
                granularity=granularity,
                start_ms=chunk_start,
                end_ms=chunk_end,
                limit=page_size,
                use_history_endpoint=use_history_endpoint,
            )
            for b in page:
                out[b.ts] = b
            # Step forward to just past the chunk we just pulled (use latest bar+1ms
            # if available, else advance by full chunk size)
            if page:
                latest_ms = int(page[-1].ts.timestamp() * 1000)
                chunk_start = max(chunk_end + 1, latest_ms + 1)
            else:
                chunk_start = chunk_end + 1
        return sorted(out.values(), key=lambda b: b.ts)

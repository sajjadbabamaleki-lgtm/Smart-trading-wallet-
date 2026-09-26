"""Read-only Hyperliquid market data for paper trading.

Only the public /info endpoint is used. Nothing in this package can sign or
send an order.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import UTC, datetime

import pandas as pd

INFO_URL = "https://api.hyperliquid.xyz/info"
DAY_MS = 86_400_000
PAGE_LIMIT = 500  # rows per fundingHistory response


def _post(payload: dict[str, object], retries: int = 5) -> object:
    body = json.dumps(payload).encode()
    for attempt in range(retries):
        req = urllib.request.Request(  # noqa: S310 - fixed https endpoint
            INFO_URL, data=body, headers={"content-type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                return json.loads(resp.read())
        except OSError:
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def perp_universe() -> list[str]:
    """Names of all listed, non-delisted perps."""
    meta = _post({"type": "meta"})
    assert isinstance(meta, dict)
    return [a["name"] for a in meta["universe"] if not a.get("isDelisted", False)]


def candles(coin: str, interval: str, start_ms: int = 0) -> pd.DataFrame:
    """OHLCV candles indexed by UTC open time. Volume `v` is in base units."""
    now = int(datetime.now(UTC).timestamp() * 1000)
    rows = _post(
        {
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": now},
        }
    )
    assert isinstance(rows, list)
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "v", "close_ms"])
    df = pd.DataFrame(rows)
    out = pd.DataFrame(
        {
            "open": df["o"].astype(float).to_numpy(),
            "high": df["h"].astype(float).to_numpy(),
            "low": df["l"].astype(float).to_numpy(),
            "close": df["c"].astype(float).to_numpy(),
            "v": df["v"].astype(float).to_numpy(),
            "close_ms": df["T"].astype("int64").to_numpy(),
        },
        index=pd.to_datetime(df["t"].astype("int64"), unit="ms", utc=True),
    )
    return out[~out.index.duplicated()].sort_index()


def daily_funding(coin: str, start_ms: int) -> pd.Series:
    """Sum of hourly funding rates per UTC day, paging through the 500-row limit."""
    out: list[dict[str, object]] = []
    cursor = start_ms
    now = int(datetime.now(UTC).timestamp() * 1000)
    while cursor < now:
        rows = _post({"type": "fundingHistory", "coin": coin, "startTime": cursor})
        assert isinstance(rows, list)
        if not rows:
            break
        out.extend(rows)
        last = int(rows[-1]["time"])
        if len(rows) < PAGE_LIMIT or last <= cursor:
            break
        cursor = last + 1
    if not out:
        return pd.Series(dtype=float)
    df = pd.DataFrame(out)
    t = pd.to_datetime(df["time"].astype("int64"), unit="ms", utc=True).dt.floor("D")
    return pd.Series(df["fundingRate"].astype(float).to_numpy(), index=t).groupby(level=0).sum()

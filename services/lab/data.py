"""The lab's dataset: candles and funding for a fixed list of assets, cached.

Hyperliquid serves only its most recent 5,000 candles, so the cache also
preserves history that would otherwise roll out of reach. Cached files live
under `data/lab/` (git-ignored).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from services.analyst.candles import (
    Candle,
    fetch_hyperliquid,
    fetch_hyperliquid_funding,
    validate_series,
)

ASSETS: Final = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT")
"""The same ten assets as the portfolio backtest, fixed before any lab result."""
INTERVAL: Final = "4h"
CACHE_DIR: Final = Path("data/lab")

HOLDOUT_START: Final = datetime(2025, 12, 22, tzinfo=UTC)
"""Nine months before the lab was built (2026-09-22). Nothing after this date
is used while developing a strategy.

Honest caveat: the first trend strategy and the funding carry were tested on
periods that include these months, before this lab existed. For those two the
holdout is not clean; for every strategy added through the lab, it is."""

DEV_WARMUP: Final = timedelta(days=101)
"""History every strategy may read before the development window starts —
the longest lookback in the catalogue (100 days) plus a day. One common start
keeps trials comparable."""


@dataclass(frozen=True)
class Dataset:
    candles: dict[str, list[Candle]]
    funding: dict[str, dict[datetime, float]]

    @property
    def start(self) -> datetime:
        return min(c[0].open_time for c in self.candles.values())

    @property
    def end(self) -> datetime:
        return max(c[-1].open_time for c in self.candles.values())


def _path(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol}_{INTERVAL}.json"


def save(symbol: str, candles: list[Candle], funding: dict[datetime, float]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "candles": [
            [c.open_time.isoformat(), c.open, c.high, c.low, c.close, c.volume] for c in candles
        ],
        "funding": {t.isoformat(): r for t, r in funding.items()},
    }
    _path(symbol).write_text(json.dumps(payload))


def _merge(
    old: dict[str, Any] | None, candles: list[Candle], funding: dict[datetime, float]
) -> tuple[list[Candle], dict[datetime, float]]:
    """Keep history already cached that the venue no longer serves."""
    if old is None:
        return candles, funding
    merged = {
        datetime.fromisoformat(row[0]): Candle(datetime.fromisoformat(row[0]), *row[1:])
        for row in old["candles"]
    }
    merged.update({c.open_time: c for c in candles})
    rates = {datetime.fromisoformat(t): r for t, r in old["funding"].items()}
    rates.update(funding)
    return validate_series(list(merged.values()), INTERVAL), rates


def fetch(
    info: Any, symbols: tuple[str, ...] = ASSETS, *, now: datetime
) -> tuple[list[str], list[str]]:
    """Download and cache every asset. Returns a report line per asset, and
    the symbols that failed."""
    report: list[str] = []
    failed: list[str] = []
    for symbol in symbols:
        try:
            candles = fetch_hyperliquid(info, symbol, INTERVAL, now=now)
            funding = fetch_hyperliquid_funding(info, symbol, start=candles[0].open_time, end=now)
            old = json.loads(_path(symbol).read_text()) if _path(symbol).exists() else None
            candles, funding = _merge(old, candles, funding)
            save(symbol, candles, funding)
            report.append(
                f"{symbol}: {len(candles)} candles, {candles[0].open_time:%Y-%m-%d} → "
                f"{candles[-1].open_time:%Y-%m-%d}"
            )
        except Exception as exc:  # noqa: BLE001 — one failed asset must not stop the rest
            report.append(f"{symbol}: FAILED ({type(exc).__name__}: {exc})")
            failed.append(symbol)
    return report, failed


def load(symbols: tuple[str, ...] = ASSETS) -> Dataset:
    candles: dict[str, list[Candle]] = {}
    funding: dict[str, dict[datetime, float]] = {}
    for symbol in symbols:
        path = _path(symbol)
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        candles[symbol] = [
            Candle(datetime.fromisoformat(row[0]), *row[1:]) for row in payload["candles"]
        ]
        funding[symbol] = {datetime.fromisoformat(t): r for t, r in payload["funding"].items()}
    if not candles:
        raise FileNotFoundError("no cached data; run `python -m services.lab.cli fetch` first")
    return Dataset(candles=candles, funding=funding)

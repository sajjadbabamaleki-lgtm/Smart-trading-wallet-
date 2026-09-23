"""Daily history of every Binance USD-M perpetual, delisted ones included.

Binance publishes its complete futures history as monthly files at
data.binance.vision (served from an S3 bucket). Unlike an exchange API, the
bucket keeps coins that were later delisted — LUNA, FTT and the rest — so a
cross-sectional test on it is free of survivorship bias: the coins that
collapsed are in the sample, as they were in the market.

Hyperliquid's own history is too short for this (5,000 candles), and its
prices track Binance's closely, so Binance is the research dataset; trading
would still happen on Hyperliquid.
"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from services.lab.data import CACHE_DIR

BUCKET: Final = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
KLINES_PREFIX: Final = "data/futures/um/monthly/klines/"
FUNDING_PREFIX: Final = "data/futures/um/monthly/fundingRate/"
BINANCE_DIR: Final = CACHE_DIR / "binance"
FIRST_MONTH: Final = "2020-01"
WORKERS: Final = 48

EXCLUDED_BASES: Final = frozenset(
    {"USDC", "BUSD", "TUSD", "USDP", "FDUSD", "DAI", "EUR", "GBP", "AEUR", "USDE", "BTCDOM"}
)
"""Stablecoins, currencies and index contracts: not the coins the strategy is about."""
_SYMBOL = re.compile(r"^[0-9A-Z]+USDT$")


@dataclass(frozen=True)
class Day:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    quote_volume: float
    """Traded value in USDT."""


@dataclass(frozen=True)
class Market:
    days: dict[str, list[Day]]
    funding: dict[str, dict[datetime, float]]
    """Funding per symbol, summed per UTC day. Longs pay a positive rate."""


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def _get(url: str) -> bytes:
    if not url.startswith("https://"):
        raise ValueError(f"refusing a non-https URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "smart-trading-wallet-lab"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return bytes(response.read())


def list_keys(prefix: str, *, delimiter: bool, get: Callable[[str], bytes] = _get) -> list[str]:
    """Every key (or, with `delimiter`, every sub-folder) under a bucket prefix."""
    out: list[str] = []
    marker = ""
    tag = "Prefix" if delimiter else "Key"
    while True:
        query = {"prefix": prefix, "marker": marker}
        if delimiter:
            query["delimiter"] = "/"
        body = get(f"{BUCKET}?{urllib.parse.urlencode(query)}").decode()
        found = re.findall(rf"<{tag}>([^<]+)</{tag}>", body)
        out.extend(f for f in found if f != prefix)
        if "<IsTruncated>true</IsTruncated>" not in body:
            return out
        next_marker = re.search(r"<NextMarker>([^<]+)</NextMarker>", body)
        marker = next_marker.group(1) if next_marker else found[-1]


def eligible_symbol(symbol: str) -> bool:
    return bool(_SYMBOL.match(symbol)) and symbol.removesuffix("USDT") not in EXCLUDED_BASES


def _rows(blob: bytes) -> Iterable[list[str]]:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for name in archive.namelist():
            text = archive.read(name).decode()
            for row in csv.reader(io.StringIO(text)):
                if row and row[0][:1].isdigit():  # newer files carry a header
                    yield row


def parse_klines(blob: bytes) -> list[Day]:
    return [
        Day(
            datetime.fromtimestamp(int(r[0]) / 1000, tz=UTC),
            float(r[1]),
            float(r[2]),
            float(r[3]),
            float(r[4]),
            float(r[7]),
        )
        for r in _rows(blob)
    ]


def parse_funding(blob: bytes) -> list[tuple[datetime, float]]:
    return [(datetime.fromtimestamp(int(r[0]) / 1000, tz=UTC), float(r[-1])) for r in _rows(blob)]


def _month(key: str) -> str:
    match = re.search(r"(\d{4}-\d{2})\.zip$", key)
    return match.group(1) if match else ""


def _path(symbol: str) -> Path:
    return BINANCE_DIR / f"{symbol}.json"


def _download_klines(symbol: str, get: Callable[[str], bytes]) -> None:
    keys = [
        k
        for k in list_keys(f"{KLINES_PREFIX}{symbol}/1d/", delimiter=False, get=get)
        if k.endswith(".zip") and _month(k) >= FIRST_MONTH
    ]
    days: dict[datetime, Day] = {}
    for key in sorted(keys):
        for day in parse_klines(get(f"{BUCKET}/{key}")):
            days[day.time] = day
    rows = [
        [d.time.isoformat(), d.open, d.high, d.low, d.close, d.quote_volume]
        for d in (days[t] for t in sorted(days))
    ]
    _path(symbol).write_text(json.dumps({"days": rows, "funding": {}, "funding_done": False}))


def _download_funding(symbol: str, get: Callable[[str], bytes]) -> None:
    keys = [
        k
        for k in list_keys(f"{FUNDING_PREFIX}{symbol}/", delimiter=False, get=get)
        if k.endswith(".zip") and _month(k) >= FIRST_MONTH
    ]
    rates: dict[str, float] = {}
    for key in sorted(keys):
        for time, rate in parse_funding(get(f"{BUCKET}/{key}")):
            rates[time.isoformat()] = rate
    payload = json.loads(_path(symbol).read_text())
    payload["funding"], payload["funding_done"] = rates, True
    _path(symbol).write_text(json.dumps(payload))


def _parallel(work: Callable[[str], None], symbols: list[str], workers: int) -> list[str]:
    def one(symbol: str) -> str | None:
        try:
            work(symbol)
        except Exception:  # noqa: BLE001 — one symbol must not stop the rest
            return symbol
        return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [s for s in pool.map(one, symbols) if s is not None]


def fetch(
    *, get: Callable[[str], bytes] = _get, workers: int = WORKERS
) -> tuple[list[str], list[str]]:
    """Cache every eligible perpetual's daily klines and funding. Resumes:
    symbols already cached are skipped. Returns the symbols cached and those
    that failed."""
    BINANCE_DIR.mkdir(parents=True, exist_ok=True)
    folders = list_keys(KLINES_PREFIX, delimiter=True, get=get)
    symbols = sorted(
        s for f in folders if eligible_symbol(s := f.removeprefix(KLINES_PREFIX).strip("/"))
    )
    missing = [s for s in symbols if not _path(s).exists()]
    failed = _parallel(lambda s: _download_klines(s, get), missing, workers)
    pending = [
        s
        for s in symbols
        if _path(s).exists() and not json.loads(_path(s).read_text()).get("funding_done", True)
    ]
    failed += _parallel(lambda s: _download_funding(s, get), pending, workers)
    return [s for s in symbols if s not in failed], failed


def funding_by_hour(symbol: str) -> dict[datetime, float]:
    """A symbol's funding events keyed to the hour. Binance stamps them a few
    milliseconds after the hour, so an exact-time lookup would miss them."""
    path = _path(symbol)
    if not path.exists():
        return {}
    out: dict[datetime, float] = {}
    for stamp, rate in json.loads(path.read_text())["funding"].items():
        hour = datetime.fromisoformat(stamp).replace(minute=0, second=0, microsecond=0)
        out[hour] = out.get(hour, 0.0) + rate
    return out


def load() -> Market:
    if not BINANCE_DIR.exists():
        raise FileNotFoundError("no Binance data; run `python -m services.lab.cli binance-fetch`")
    days: dict[str, list[Day]] = {}
    funding: dict[str, dict[datetime, float]] = {}
    for path in sorted(BINANCE_DIR.glob("*.json")):
        payload = json.loads(path.read_text())
        if not payload["days"]:
            continue
        symbol = path.stem
        days[symbol] = [Day(datetime.fromisoformat(r[0]), *r[1:]) for r in payload["days"]]
        daily: dict[datetime, float] = {}
        for stamp, rate in payload["funding"].items():
            t = datetime.fromisoformat(stamp)
            day = t.replace(hour=0, minute=0, second=0, microsecond=0)
            daily[day] = daily.get(day, 0.0) + rate
        funding[symbol] = daily
    if not days:
        raise FileNotFoundError("no Binance data; run `python -m services.lab.cli binance-fetch`")
    return Market(days=days, funding=funding)

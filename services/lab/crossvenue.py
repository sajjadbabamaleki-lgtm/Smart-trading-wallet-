"""Cross-venue funding arbitrage: Hyperliquid against dYdX v4.

Both venues charge hourly funding on the same coins, but their rates are set
by different traders and often differ. Short the perpetual on the venue that
pays more, long it on the one that pays less: the price moves cancel and the
difference in funding is earned. Both legs are perpetuals, so neither needs
the full notional in cash, unlike spot-perp carry. Moving collateral between
two venues is a nuisance that keeps large funds out, which is why the gap
might persist. Both venues are self-custodial.

Rules, fixed before any result:
- coins: the lab's ten, on both venues, hourly funding from both;
- signal: the spread (Hyperliquid rate - dYdX rate) averaged over the past 72
  hours, using only rates already paid;
- enter when that average annualises beyond 20% either way (short the venue
  that pays more); exit when it falls below 5% or changes sign;
- at most 5 coins at once, each with a fifth of capital split across the two
  venues, 3x leverage on each leg: notional per coin = capital / 5 x 1.5;
- costs per round trip: both legs opened and closed, 0.045% (Hyperliquid) and
  0.05% (dYdX) taker fees plus 0.05% slippage per fill; and when price has
  moved 15% since the last rebalance, collateral is moved between venues by
  trading that fraction of the notional on both legs, at the same costs.

Not modelled: the price gap between the two venues at entry and exit (covered
roughly by the slippage), transfer delays, and liquidation from a jump larger
than 15% within an hour; a live bot must rebalance continuously.
"""

from __future__ import annotations

import functools
import json
import statistics
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from services.analyst.candles import fetch_hyperliquid_funding, with_rate_limit_retry
from services.lab.data import ASSETS, CACHE_DIR
from services.lab.xsection import XResult

NAME: Final = "hl-dydx-funding-arb"
DIR: Final = CACHE_DIR / "crossvenue"
DYDX_INDEXER: Final = "https://indexer.dydx.trade/v4"
DYDX_START: Final = datetime(2023, 11, 1, tzinfo=UTC)
LOOKBACK_HOURS: Final = 72
ENTRY_APR: Final = 0.20
EXIT_APR: Final = 0.05
MAX_COINS: Final = 5
LEVERAGE: Final = 3.0
HL_FEE: Final = 0.00045
DYDX_FEE: Final = 0.0005
SLIPPAGE: Final = 0.0005
REBALANCE_MOVE: Final = 0.15
MAX_DRAWDOWN: Final = -0.20
"""Pre-registered: a market-neutral book has no long-only basket to compare with."""
HOURS_PER_YEAR: Final = 24 * 365
HOUR: Final = timedelta(hours=1)
SOURCE: Final = (
    "Cross-venue funding dispersion: two perpetual markets on one coin, priced by different "
    "traders; the carry literature (Schmeling, Schrimpf & Todorov 2023, BIS WP 1087) shows "
    "funding is large and time-varying. Short the venue paying more, long the one paying less."
)
ROUND_TRIP: Final = 2 * (HL_FEE + DYDX_FEE + 2 * SLIPPAGE)
"""Open and close both legs, as a fraction of one leg's notional."""


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def _get_json(url: str) -> Any:
    if not url.startswith("https://"):
        raise ValueError(f"refusing a non-https URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "smart-trading-wallet-lab"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read())


def fetch_dydx(
    coin: str,
    *,
    start: datetime,
    end: datetime,
    get_json: Callable[[str], Any] = _get_json,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[datetime, float], dict[datetime, float]]:
    """Hourly funding rates and oracle prices for COIN-USD, walked backwards
    from `end` a page (100 rows) at a time."""
    rates: dict[datetime, float] = {}
    prices: dict[datetime, float] = {}
    cursor = end
    while cursor > start:
        stamp = cursor.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        url = f"{DYDX_INDEXER}/historicalFunding/{coin}-USD?limit=100&effectiveBeforeOrAt={stamp}"
        page = with_rate_limit_retry(functools.partial(get_json, url)).get("historicalFunding", [])
        if not page:
            break
        oldest = cursor
        for row in page:
            at = datetime.fromisoformat(row["effectiveAt"].replace("Z", "+00:00"))
            hour = at.replace(minute=0, second=0, microsecond=0)
            rates[hour] = float(row["rate"])
            prices[hour] = float(row["price"])
            oldest = min(oldest, at)
        if oldest >= cursor:
            break
        cursor = oldest - timedelta(seconds=1)
        sleep(0.2)
    return rates, prices


def fetch(info: Any, *, now: datetime, get_json: Callable[[str], Any] = _get_json) -> list[str]:
    """Cache both venues' funding for the ten coins. Returns the coins that failed."""
    DIR.mkdir(parents=True, exist_ok=True)
    failed = []
    for coin in ASSETS:
        try:
            hl = fetch_hyperliquid_funding(info, coin, start=DYDX_START, end=now)
            dydx, prices = fetch_dydx(coin, start=DYDX_START, end=now, get_json=get_json)
            payload = {
                "hyperliquid": {t.isoformat(): r for t, r in hl.items()},
                "dydx": {t.isoformat(): r for t, r in dydx.items()},
                "price": {t.isoformat(): p for t, p in prices.items()},
            }
            (DIR / f"{coin}.json").write_text(json.dumps(payload))
        except Exception:  # noqa: BLE001 — one coin must not stop the rest
            failed.append(coin)
    return failed


@dataclass(frozen=True)
class Rates:
    hyperliquid: dict[datetime, float]
    dydx: dict[datetime, float]
    price: dict[datetime, float]


def load() -> dict[str, Rates]:
    out = {}
    for coin in ASSETS:
        path = DIR / f"{coin}.json"
        if not path.exists():
            continue
        raw = json.loads(path.read_text())
        out[coin] = Rates(
            *(
                {datetime.fromisoformat(t): v for t, v in raw[k].items()}
                for k in ("hyperliquid", "dydx", "price")
            )
        )
    if not out:
        raise FileNotFoundError(
            "no cross-venue data; run `python -m services.lab.cli xvenue-fetch`"
        )
    return out


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


@dataclass
class _Pair:
    coin: str
    side: int
    """+1: short Hyperliquid, long dYdX (Hyperliquid pays more); -1: the reverse."""
    notional: float
    anchor: float


def run_arb(data: dict[str, Rates] | None = None) -> XResult:
    rates = data or load()
    common = {c: sorted(set(r.hyperliquid) & set(r.dydx) & set(r.price)) for c, r in rates.items()}
    hours = sorted({h for hs in common.values() for h in hs})
    spreads = {c: {h: rates[c].hyperliquid[h] - rates[c].dydx[h] for h in common[c]} for c in rates}
    history: dict[str, list[float]] = {c: [] for c in rates}

    equity = 1.0
    open_: dict[str, _Pair] = {}
    daily: dict[datetime, float] = {}
    costs = earned = turnover = 0.0
    for hour in hours:
        start = equity
        # Settle this hour's funding and rebalancing for open pairs.
        for coin, pair in list(open_.items()):
            if hour not in spreads[coin]:
                continue
            payment = pair.side * pair.notional * spreads[coin][hour]
            equity += payment
            earned += payment
            price = rates[coin].price[hour]
            move = abs(price / pair.anchor - 1)
            if move >= REBALANCE_MOVE:
                cost = pair.notional * move * ROUND_TRIP
                equity -= cost
                costs += cost
                pair.anchor = price
        # Decide with rates already paid (this hour's included, now settled).
        for coin in rates:
            if hour not in spreads[coin]:
                continue
            history[coin].append(spreads[coin][hour])
            window = history[coin][-LOOKBACK_HOURS:]
            if len(window) < LOOKBACK_HOURS:
                continue
            apr = statistics.fmean(window) * HOURS_PER_YEAR
            held = open_.get(coin)
            if held is not None:
                if abs(apr) < EXIT_APR or apr * held.side < 0:
                    cost = held.notional * ROUND_TRIP / 2
                    equity -= cost
                    costs += cost
                    turnover += held.notional
                    del open_[coin]
                continue
            if abs(apr) >= ENTRY_APR and len(open_) < MAX_COINS:
                notional = equity / MAX_COINS * LEVERAGE / 2
                cost = notional * ROUND_TRIP / 2
                equity -= cost
                costs += cost
                turnover += notional
                open_[coin] = _Pair(coin, 1 if apr > 0 else -1, notional, rates[coin].price[hour])
        day = hour.replace(hour=0)
        daily[day] = (1 + daily.get(day, 0.0)) * (equity / start) - 1 if start > 0 else 0.0
    days = sorted(daily)
    zeros = [0.0] * len(days)
    return XResult(NAME, days, [daily[d] for d in days], zeros, turnover, costs, -earned)


STRUCTURAL_NAME: Final = "hl-dydx-structural"
STRUCTURAL_SOURCE: Final = (
    "Hyperliquid's funding formula adds a fixed interest component (0.01% per 8 hours, about "
    "11% a year) that dYdX v4's does not, so Hyperliquid's funding sits structurally above "
    "dYdX's. Registered after the fetch showed Hyperliquid's median at +10.9% and dYdX's near 0 "
    "on every coin, so only the holdout counts."
)


def run_structural(data: dict[str, Rates] | None = None) -> XResult:
    """Always short Hyperliquid and long dYdX on every coin, equal weights,
    3x per leg; the same costs and rebalancing as run_arb, and no signal."""
    rates = data or load()
    common = {c: sorted(set(r.hyperliquid) & set(r.dydx) & set(r.price)) for c, r in rates.items()}
    hours = sorted({h for hs in common.values() for h in hs})
    equity = 1.0
    open_: dict[str, _Pair] = {}
    daily: dict[datetime, float] = {}
    costs = earned = turnover = 0.0
    for hour in hours:
        start = equity
        for coin, r in rates.items():
            if hour not in r.hyperliquid or hour not in r.dydx or hour not in r.price:
                continue
            pair = open_.get(coin)
            if pair is None:
                notional = equity / len(rates) * LEVERAGE / 2
                cost = notional * ROUND_TRIP / 2
                equity -= cost
                costs += cost
                turnover += notional
                open_[coin] = _Pair(coin, 1, notional, r.price[hour])
                continue
            payment = pair.notional * (r.hyperliquid[hour] - r.dydx[hour])
            equity += payment
            earned += payment
            move = abs(r.price[hour] / pair.anchor - 1)
            if move >= REBALANCE_MOVE:
                cost = pair.notional * move * ROUND_TRIP
                equity -= cost
                costs += cost
                pair.anchor = r.price[hour]
        day = hour.replace(hour=0)
        daily[day] = (1 + daily.get(day, 0.0)) * (equity / start) - 1 if start > 0 else 0.0
    days = sorted(daily)
    zeros = [0.0] * len(days)
    return XResult(STRUCTURAL_NAME, days, [daily[d] for d in days], zeros, turnover, costs, -earned)

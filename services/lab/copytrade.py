"""Does copying a winning trader work? Test the premise first: persistence.

Copy trading pays only if traders who did well in one period keep doing well
in the next. The evidence from social-trading platforms is weak: Apesteguia,
Oechssler & Weidenholzer (2020, Management Science) find that copying mainly
raises risk-taking, and past rankings are dominated by luck and leverage.

Hyperliquid makes the test possible because every account is public. For a
pool of accounts from its leaderboard, the study reads each one's PnL history
and asks, at a selection date 90 days ago:

    rank traders by return over the 90 days before it (period A),
    then look at their return over the 90 days after it (period B).

If winners persist, the rank correlation between A and B is positive and the
top decile of A stays profitable in B. Those checks are fixed below, before
any result.

Bias, stated plainly: the pool comes from today's leaderboard, so accounts
that blew up during period B are under-represented. That bias favours copy
trading; a failed test is therefore conclusive, a passed one is not yet proof
(copying also adds delay and slippage, which this study does not charge).
"""

from __future__ import annotations

import functools
import json
import math
import statistics
import time
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from services.analyst.candles import with_rate_limit_retry
from services.lab.data import CACHE_DIR

LEADERBOARD_URL: Final = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
COPY_DIR: Final = CACHE_DIR / "copytrade"
PERIOD: Final = timedelta(days=90)
POOL_SIZE: Final = 400
MIN_ACCOUNT_VALUE: Final = 10_000.0
MIN_EQUITY_AT_START: Final = 1_000.0
MAX_GAP: Final = timedelta(days=7)
"""A history point must lie within this of a period boundary, or the trader is skipped."""
DECILE: Final = 0.1
MAX_P_VALUE: Final = 0.05
PAUSE_SECONDS: Final = 0.3


@dataclass(frozen=True)
class Candidate:
    address: str
    account_value: float


@dataclass(frozen=True)
class History:
    equity: list[tuple[datetime, float]]
    pnl: list[tuple[datetime, float]]


@dataclass(frozen=True)
class Outcome:
    address: str
    return_a: float
    return_b: float


@dataclass(frozen=True)
class Study:
    selection_date: datetime
    pool: int
    outcomes: list[Outcome]
    spearman: float
    p_value: float
    top_median_b: float
    top_profitable_b: float
    pool_median_b: float
    bottom_median_b: float

    @property
    def checks(self) -> dict[str, bool]:
        return {
            f"rank correlation A→B positive (p < {MAX_P_VALUE})": self.spearman > 0
            and self.p_value < MAX_P_VALUE,
            "top decile of A profitable in B (median)": self.top_median_b > 0,
            "top decile beats the pool in B": self.top_median_b > self.pool_median_b,
        }


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def parse_leaderboard(payload: Any) -> list[Candidate]:
    rows = payload["leaderboardRows"] if isinstance(payload, dict) else payload
    out = []
    for row in rows:
        try:
            out.append(Candidate(str(row["ethAddress"]).lower(), float(row["accountValue"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def select_pool(candidates: Sequence[Candidate], size: int = POOL_SIZE) -> list[Candidate]:
    """The largest accounts, not the most profitable: ranking by all-time PnL
    would select on period B itself."""
    eligible = [c for c in candidates if c.account_value >= MIN_ACCOUNT_VALUE]
    return sorted(eligible, key=lambda c: -c.account_value)[:size]


def parse_portfolio(payload: Any) -> History:
    """The `portfolio` info response: [[window, {accountValueHistory, pnlHistory}], …].
    Perpetuals-only all-time history when present, else the account's."""
    windows = dict(payload) if isinstance(payload, list) else payload
    data = windows.get("perpAllTime") or windows["allTime"]

    def series(key: str) -> list[tuple[datetime, float]]:
        return sorted(
            (datetime.fromtimestamp(int(t) / 1000, tz=UTC), float(v)) for t, v in data[key]
        )

    return History(equity=series("accountValueHistory"), pnl=series("pnlHistory"))


def _cache_path(address: str) -> Path:
    return COPY_DIR / f"{address}.json"


def fetch(
    info: Any,
    *,
    get_json: Callable[[str], Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, list[str]]:
    """Download the leaderboard and each pool account's history. Returns the
    pool size and the addresses that failed."""
    get_json = get_json or _get_json
    pool = select_pool(parse_leaderboard(with_rate_limit_retry(lambda: get_json(LEADERBOARD_URL))))
    COPY_DIR.mkdir(parents=True, exist_ok=True)
    (COPY_DIR / "pool.json").write_text(json.dumps([c.address for c in pool]))
    failed = []
    for candidate in pool:
        try:
            address = candidate.address
            payload = with_rate_limit_retry(functools.partial(info.portfolio, address))
            parse_portfolio(payload)  # refuse to cache what cannot be read
            _cache_path(address).write_text(json.dumps(payload))
        except Exception:  # noqa: BLE001 — one account must not stop the rest
            failed.append(address)
        sleep(PAUSE_SECONDS)
    return len(pool), failed


def _get_json(url: str) -> Any:
    if not url.startswith("https://"):
        raise ValueError(f"refusing a non-https URL: {url}")
    headers = {"User-Agent": "smart-trading-wallet-lab"}
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 — https checked above
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read())


def load() -> dict[str, History]:
    pool_path = COPY_DIR / "pool.json"
    if not pool_path.exists():
        raise FileNotFoundError("no cached traders; run `python -m services.lab.cli copy-fetch`")
    histories = {}
    for address in json.loads(pool_path.read_text()):
        path = _cache_path(address)
        if path.exists():
            histories[address] = parse_portfolio(json.loads(path.read_text()))
    return histories


# ---------------------------------------------------------------------------
# Study
# ---------------------------------------------------------------------------


def _at(points: list[tuple[datetime, float]], when: datetime) -> float | None:
    """The value at the history point nearest `when`, if one is close enough."""
    if not points:
        return None
    nearest = min(points, key=lambda p: abs(p[0] - when))
    return nearest[1] if abs(nearest[0] - when) <= MAX_GAP else None


def outcome(address: str, history: History, selection: datetime) -> Outcome | None:
    """Returns over A and B: PnL (which excludes deposits and withdrawals)
    divided by the equity at the start of each period."""
    start, end = selection - PERIOD, selection + PERIOD
    pnl = [_at(history.pnl, t) for t in (start, selection, end)]
    equity = [_at(history.equity, t) for t in (start, selection)]
    if any(v is None for v in (*pnl, *equity)):
        return None
    p0, p1, p2 = (float(v) for v in pnl)  # type: ignore[arg-type]
    e0, e1 = (float(v) for v in equity)  # type: ignore[arg-type]
    if e0 < MIN_EQUITY_AT_START or e1 < MIN_EQUITY_AT_START:
        return None
    return Outcome(address, (p1 - p0) / e0, (p2 - p1) / e1)


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def spearman(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """Rank correlation and its one-sided p-value (large-sample normal approximation)."""
    n = len(a)
    if n < 3:  # noqa: PLR2004
        return 0.0, 1.0
    ra, rb = _ranks(a), _ranks(b)
    if statistics.pstdev(ra) == 0 or statistics.pstdev(rb) == 0:
        return 0.0, 1.0
    rho = statistics.correlation(ra, rb)
    return rho, 1 - statistics.NormalDist().cdf(rho * math.sqrt(n - 1))


def run_study(histories: dict[str, History], *, now: datetime) -> Study:
    selection = now - PERIOD
    outcomes = [
        o
        for address, history in histories.items()
        if (o := outcome(address, history, selection)) is not None
    ]
    if len(outcomes) < 1 / DECILE:
        raise ValueError(f"only {len(outcomes)} traders have history covering both periods")
    ranked = sorted(outcomes, key=lambda o: -o.return_a)
    k = max(1, round(len(ranked) * DECILE))
    top, bottom = ranked[:k], ranked[-k:]
    rho, p = spearman([o.return_a for o in outcomes], [o.return_b for o in outcomes])
    return Study(
        selection_date=selection,
        pool=len(histories),
        outcomes=outcomes,
        spearman=rho,
        p_value=p,
        top_median_b=statistics.median(o.return_b for o in top),
        top_profitable_b=sum(o.return_b > 0 for o in top) / k,
        pool_median_b=statistics.median(o.return_b for o in outcomes),
        bottom_median_b=statistics.median(o.return_b for o in bottom),
    )

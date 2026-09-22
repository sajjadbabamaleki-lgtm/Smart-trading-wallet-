"""Every trial, recorded; and the Deflated Sharpe Ratio that accounts for them.

Try enough strategies on the same data and one will look excellent by chance
alone. The Deflated Sharpe Ratio (Bailey & López de Prado, 2014, "The Deflated
Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and
Non-Normality") answers the honest question: given how many strategies were
tried and how much their results varied, what is the probability that the
best one's true Sharpe ratio is above zero?

    SR* = sqrt(V) x ((1 - g) Φ⁻¹(1 - 1/N) + g Φ⁻¹(1 - 1/(N e)))
    DSR = Φ((SR - SR*) sqrt(T - 1) / sqrt(1 - skew SR + (kurt - 1)/4 SR²))

N is the number of trials, V the variance of their Sharpe ratios, g the
Euler-Mascheroni constant, T the number of return observations. Sharpe ratios
here are per 4h candle, the frequency the returns are measured at.

The log is append-only JSON lines under data/lab/; nothing is ever removed
from it, so a trial cannot be forgotten.
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from services.lab.data import CACHE_DIR
from services.lab.engine import LabResult

TRIALS_PATH: Final = CACHE_DIR / "trials.jsonl"
EULER_GAMMA: Final = 0.5772156649015329
PRIOR_TRIALS: Final = 6
"""Tests run on this data before the lab existed: the trend strategy on SOL,
BTC, ETH and the ten-asset portfolio, and funding carry in two forms. They
count toward N even though their Sharpe ratios are not in the log."""


def record(result: LabResult, window: str, path: Path = TRIALS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "time": datetime.now(UTC).isoformat(),
        "strategy": result.strategy,
        "window": window,
        "sharpe_per_bar": result.sharpe_per_bar,
        "observations": result.observations,
        "skew": result.skew,
        "kurtosis": result.kurtosis,
        "total_return": result.full.total_return,
        "trades": result.full.trades,
        "max_drawdown": result.full.max_drawdown,
    }
    with path.open("a") as log:
        log.write(json.dumps(entry) + "\n")


def load(path: Path = TRIALS_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def development_trials(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The latest development result per strategy. Re-running an unchanged
    strategy is not a new trial; a changed strategy must carry a new name."""
    latest: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if entry["window"] == "development":
            latest[entry["strategy"]] = entry
    return latest


def holdout_used(strategy: str, entries: list[dict[str, Any]]) -> bool:
    return any(e["strategy"] == strategy and e["window"] == "holdout" for e in entries)


def expected_max_sharpe(sharpes: list[float], trials: int) -> float:
    """SR*: the best Sharpe ratio expected from `trials` strategies with no edge."""
    if trials < 2 or len(sharpes) < 2:  # noqa: PLR2004
        return 0.0
    normal = statistics.NormalDist()
    spread = math.sqrt(statistics.variance(sharpes))
    return spread * (
        (1 - EULER_GAMMA) * normal.inv_cdf(1 - 1 / trials)
        + EULER_GAMMA * normal.inv_cdf(1 - 1 / (trials * math.e))
    )


def deflated_sharpe(
    sharpe: float, observations: int, skew: float, kurtosis: float, benchmark: float
) -> float:
    if observations < 2:  # noqa: PLR2004
        return 0.5
    denominator = 1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe**2
    if denominator <= 0:
        return 0.5
    z = (sharpe - benchmark) * math.sqrt(observations - 1) / math.sqrt(denominator)
    return statistics.NormalDist().cdf(z)


def deflated_for(entry: dict[str, Any], trials: dict[str, dict[str, Any]]) -> float:
    sharpes = [t["sharpe_per_bar"] for t in trials.values()]
    benchmark = expected_max_sharpe(sharpes, len(trials) + PRIOR_TRIALS)
    return deflated_sharpe(
        entry["sharpe_per_bar"],
        entry["observations"],
        entry["skew"],
        entry["kurtosis"],
        benchmark,
    )

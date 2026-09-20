"""One paper-trading tick: read the chart, decide, record, report.

Run on a timer. It reads the latest stored candles, computes the same features
the backtester uses, asks the same rule the same question, and writes the
answer down before the price that judges it exists.

**It refuses stale data rather than deciding on it.** A recorder that stopped,
a download that never ran, a venue that went quiet — all of them leave the
newest candle hours or days old, and a decision taken on a stale candle is
worse than no decision, because it looks exactly like a fresh one in the log.
So the age of the newest candle is checked against the interval and the run
exits rather than writing a decision it cannot stand behind.

**It writes its own history and nothing else.** No order reaches a venue, no
capital is at risk, and the mainnet block that governs the rest of the project
is not relaxed here because nothing here needs it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

from libs.config import Settings, load_settings
from libs.domain.candles import Candle, CandleRequest
from libs.domain.funding import FundingError, FundingHistory, FundingRate
from libs.information.fear_greed import SOURCE as SENTIMENT_SOURCE
from libs.information.fear_greed import Reading, SentimentError, SentimentHistory
from libs.observability import configure_logging
from libs.storage import clickhouse as ch
from libs.storage import postgres as pg
from services.research.candle_store import read_candles
from services.research.costs import CostModel
from services.research.funding_store import read_funding
from services.research.information_store import read_sentiment
from services.strategy_engine.evaluate_candles_cli import (
    FUNDING_RULES,
    MEASURED_HALF_SPREAD_BPS,
    RULES,
    SENTIMENT_RULES,
)
from services.strategy_engine.features import FeatureConfig, FeatureSet, compute
from services.strategy_engine.paper import PaperBook, PaperContext, Tick

STALENESS_ALLOWANCE: Final = 2
"""How many intervals the newest candle may be behind before a run refuses.

Two, so a timer that fires a little late or a venue that publishes a candle
slowly does not stop the loop, while a download that has not run since
yesterday does. One interval would refuse on ordinary jitter; a day's worth
would let the engine decide on yesterday's chart and record it as today's.
"""

HISTORY_DAYS: Final = 120
"""How much history to load for the features. More than the warmup needs and
far less than the store holds, because a tick should be quick."""


def _sentiment_for(series: Series, *, rule: str) -> tuple[SentimentHistory | None, str | None]:
    """The sentiment series for this tick, or why there is none to use."""
    if series.sentiment:
        try:
            return SentimentHistory.build(list(series.sentiment)), None
        except SentimentError as exc:
            return None, f"the stored sentiment series cannot be used: {exc}"
    if rule in SENTIMENT_RULES:
        return None, (
            f"{rule} needs the Fear & Greed index and none is stored. Run `make sentiment` first."
        )
    return None, None


def _reasons(features: FeatureSet, *, candles: int) -> dict[str, object]:
    """Why the rule decided what it did, in a form the log can keep.

    Stored with the decision so it can be audited later without re-running the
    feature engine against data that has since moved — which is the only way
    to check a months-old decision honestly.
    """
    return {
        "trend_regime": features.trend_regime.value,
        "volatility_regime": features.volatility_regime.value,
        "trend_bps": str(features.trend_bps),
        "momentum_bps": str(features.momentum_bps),
        "distance_from_trend_bps": str(features.distance_from_trend_bps),
        "funding_percentile": (
            None if features.funding_percentile is None else str(features.funding_percentile)
        ),
        "funding_rate_bps": (
            None if features.funding_rate_bps is None else str(features.funding_rate_bps)
        ),
        "sentiment": None if features.sentiment is None else str(features.sentiment),
        "candles": candles,
    }


@dataclass(frozen=True, slots=True)
class Series:
    """The stored data a tick reasons over, and why it might not be usable."""

    candles: tuple[Candle, ...]
    settlements: tuple[FundingRate, ...]
    sentiment: tuple[Reading, ...]


def _load(request: CandleRequest, *, venue: str, settings: Settings) -> Series:
    """Read the candles and settlements one tick needs, in one connection."""
    with ch.connect_from_settings(settings) as client:
        return Series(
            candles=tuple(read_candles(client, request, venue=venue)),
            settlements=tuple(
                read_funding(
                    client,
                    venue=venue,
                    asset=request.asset,
                    start=request.start,
                    end=request.end,
                )
            ),
            sentiment=tuple(
                read_sentiment(
                    client,
                    source=SENTIMENT_SOURCE,
                    start=request.start,
                    end=request.end,
                )
            ),
        )


def _refusal(
    series: Series, *, request: CandleRequest, now: datetime, config: FeatureConfig, venue: str
) -> str | None:
    """Why this tick must not decide, or None if it may.

    Two reasons, and both matter more than they look. Too little history means
    the features would be half-formed, which is a different feature wearing the
    same name. Stale history means the decision would be taken on a chart hours
    or days old — and in the log that is indistinguishable from a fresh one,
    which is what makes it worse than no decision at all.
    """
    if len(series.candles) < config.warmup:
        return (
            f"only {len(series.candles)} {request.interval} candles stored for "
            f"{request.asset} and {config.warmup} are needed. Run "
            f"`make history ASSET={request.asset} INTERVAL={request.interval} "
            f"SOURCE={venue}` first."
        )
    newest = series.candles[-1]
    behind = now - newest.close_time
    allowance = request.step * STALENESS_ALLOWANCE
    if behind > allowance:
        return (
            f"REFUSED: the newest {request.interval} candle for {request.asset} closed "
            f"{newest.close_time:%Y-%m-%d %H:%M} UTC, "
            f"{behind.total_seconds() / 3600:.1f} hours ago, and this run allows "
            f"{allowance.total_seconds() / 3600:.0f}.\n"
            f"The history download has not kept up. No decision was recorded."
        )
    return None


def _funding_for(
    series: Series, *, rule: str, asset: str
) -> tuple[FundingHistory | None, str | None]:
    """The funding history for this tick, or why there is none to use."""
    if series.settlements:
        try:
            return FundingHistory.build(list(series.settlements)), None
        except FundingError as exc:
            return None, f"the stored funding series cannot be used: {exc}"
    if rule in FUNDING_RULES:
        return None, (
            f"{rule} needs funding history and none is stored for {asset}. "
            f"Run `make funding ASSET={asset}` first."
        )
    return None, None


def main() -> int:
    import argparse  # noqa: PLC0415 - CLI-local

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="BTC")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--venue", default="binance", choices=["hyperliquid", "binance"])
    parser.add_argument("--rule", default="funding-extreme", choices=sorted(RULES))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="decide and print, without writing anything",
    )
    args = parser.parse_args()

    configure_logging()
    settings = load_settings()
    now = datetime.now(tz=UTC)
    request = CandleRequest(
        asset=args.asset.upper(),
        interval=args.interval,
        start=now - timedelta(days=HISTORY_DAYS),
        end=now,
    )

    config = FeatureConfig()
    series = _load(request, venue=args.venue, settings=settings)
    refusal = _refusal(series, request=request, now=now, config=config, venue=args.venue)
    if refusal is not None:
        print(refusal)
        return 2

    funding, problem = _funding_for(series, rule=args.rule, asset=request.asset)
    if problem is not None:
        print(problem)
        return 1

    candles = series.candles
    newest = candles[-1]
    sentiment, sentiment_problem = _sentiment_for(series, rule=args.rule)
    if sentiment_problem is not None:
        print(sentiment_problem)
        return 1

    features = compute(candles, config, funding, sentiment)
    decision = RULES[args.rule]().decide(features)

    reasons = _reasons(features, candles=len(candles))
    print(
        f"{request.asset} {request.interval} ({args.venue}), rule {args.rule}\n"
        f"  candle closed {newest.close_time:%Y-%m-%d %H:%M} UTC at {newest.close}\n"
        f"  decision: {decision.value}"
    )
    for key, value in reasons.items():
        if value is not None:
            print(f"    {key}: {value}")

    if args.dry_run:
        print("  dry run: nothing written")
        return 0

    context = PaperContext(
        venue=args.venue, asset=request.asset, interval=request.interval, rule=args.rule
    )
    tick = Tick(
        decision=decision,
        price=newest.close,
        candle_close=newest.close_time,
        decided_at=now,
        reasons=reasons,
    )
    with pg.connect(settings.postgres_dsn) as connection:
        book = PaperBook(
            connection=connection,
            context=context,
            costs=CostModel(half_spread_bps=MEASURED_HALF_SPREAD_BPS),
        )
        applied = book.apply(tick)

    if not applied.recorded:
        print("  already decided for this candle; nothing written")
        return 0
    if applied.closed:
        realised = applied.realised or Decimal(0)
        print(f"  closed a position, realised {realised:+.2f}")
    if applied.opened:
        print(f"  opened {decision.value} at {newest.close}")
    if not applied.closed and not applied.opened:
        print("  no position change")
    return 0


if __name__ == "__main__":
    sys.exit(main())

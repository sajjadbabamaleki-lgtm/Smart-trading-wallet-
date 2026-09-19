"""Print how the Feature Engine reads a chart right now.

This exists to be looked at. The features are the input to every decision the
system will make, so they have to be inspectable by someone who is not going to
read `features.py` — if the machine's reading of the chart disagrees with what
a person sees on it, that disagreement should be visible before a strategy is
built on top of it, not after.

It also prints how often each regime occurred over the whole stored history.
That number decides what kind of rule is worth writing at all: a
trend-following rule needs trends to exist, and "42% of the time this market is
going nowhere" is the sort of fact that should shape a strategy rather than
surprise it.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from libs.config import load_settings
from libs.domain.candles import CandleRequest
from libs.observability import configure_logging
from libs.storage import clickhouse as ch
from services.research.candle_store import read_candles
from services.strategy_engine.features import (
    FeatureConfig,
    FeatureSet,
    TrendRegime,
    feature_series,
)


def _pct(bps: Decimal) -> str:
    """Basis points as a percentage, because that is how a chart is read."""
    return f"{bps / 100:+.2f}%"


def _reading(features: FeatureSet, *, asset: str, interval: str) -> None:
    print(f"{asset}, {interval} candles, as of {features.moment:%Y-%m-%d %H:%M} UTC")
    print(f"price: {features.close}")
    print()
    rising = "rising" if features.trend_slope_bps > 0 else "falling"
    print(
        f"  trend        : {features.trend_regime.value:<6} "
        f"(averages {_pct(features.trend_bps)} apart, {rising})"
    )
    print(f"  price v trend: {_pct(features.distance_from_trend_bps)} from the slow average")
    building = "building" if features.momentum_acceleration_bps > 0 else "fading"
    print(f"  momentum     : {_pct(features.momentum_bps)} over the lookback, {building}")
    print(
        f"  volatility   : {features.volatility_regime.value:<6} "
        f"(typical range {_pct(features.atr_bps)}, "
        f"{features.volatility_ratio:.2f}x its own normal)"
    )
    print(f"  volume       : {features.relative_volume:.2f}x the recent average")
    print(f"  resistance   : {_pct(features.swing_high_bps)} above (the swing high)")
    print(f"  support      : {_pct(-features.swing_low_bps)} below (the swing low)")


def _history(sets: list[FeatureSet], *, interval: str) -> None:
    """How often each regime held, over everything stored.

    The number that decides what kind of rule is worth writing. A
    trend-following rule can only work in the share of time a trend exists, and
    that share is a property of the market rather than of the rule.
    """
    if not sets:
        return
    trends = Counter(item.trend_regime for item in sets)
    volatility = Counter(item.volatility_regime for item in sets)
    total = len(sets)

    print()
    print(
        f"over {total:,} {interval} candles "
        f"({sets[0].moment:%Y-%m-%d} to {sets[-1].moment:%Y-%m-%d}):"
    )
    for regime in TrendRegime:
        share = trends[regime] / total * 100
        print(f"  {regime.value:<6} {share:5.1f}%  ({trends[regime]:,} candles)")
    print()
    for level in volatility:
        share = volatility[level] / total * 100
        print(f"  volatility {level.value:<6} {share:5.1f}%")


def main() -> int:
    import argparse  # noqa: PLC0415 - CLI-local

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="SOL")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument(
        "--venue",
        default="hyperliquid",
        choices=["hyperliquid", "binance"],
        help="which venue's stored history to read; binance reaches back years",
    )
    args = parser.parse_args()

    configure_logging()
    settings = load_settings()
    end = datetime.now(tz=UTC)
    request = CandleRequest(
        asset=args.asset.upper(),
        interval=args.interval,
        start=end - timedelta(days=args.days),
        end=end,
    )

    with ch.connect_from_settings(settings) as client:
        candles = read_candles(client, request, venue=args.venue)

    config = FeatureConfig()
    if len(candles) < config.warmup:
        print(
            f"only {len(candles)} {request.interval} candles stored, and "
            f"{config.warmup} are needed before any feature is complete. "
            f"Run `make history ASSET={request.asset} INTERVAL={request.interval}` first."
        )
        return 1

    sets = list(feature_series(candles, config))
    _reading(sets[-1], asset=request.asset, interval=request.interval)
    _history(sets, interval=request.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

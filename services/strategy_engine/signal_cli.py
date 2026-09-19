"""What the bot thinks right now, and why.

Everything else in this package produces statistics about the past. This
produces the thing the statistics are about: a reading of the current chart, a
decision — LONG, SHORT, or WAIT — and the reasons behind it, in terms a person
can check against their own chart.

It exists because it was missing. Six rounds of backtest tables went by without
the decision itself ever being shown, which made the work impossible to judge
from outside and easy to mistake for a detour. A decision engine nobody can
look at is not a product.

**What it is honest about.** The reasons below are the indicators a trader
reads, and the verdict is a count of how many agree. That is a reasonable way
to summarise a chart and it is *not* a demonstrated edge: the trend family this
project tested first returned `NO_EDGE_FOUND` over six years and four assets,
and this agreement count has not been tested at all. So the output says so, in
the output, every time. A number that looks like a recommendation and has not
been validated is the most dangerous thing this repository could print.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

from libs.config import load_settings
from libs.domain.candles import CandleRequest
from libs.observability import configure_logging
from libs.storage import clickhouse as ch
from services.research.candle_store import read_candles
from services.strategy_engine import indicators
from services.strategy_engine.decisions import Decision
from services.strategy_engine.features import (
    FeatureConfig,
    FeatureSet,
    TrendRegime,
    compute,
)

AGREEMENT_FOR_ENTRY: Final = 3
"""How many independent signals must agree before the verdict is not WAIT.

Three of five. Chosen as a plain majority rather than fitted, because fitting
it is exactly what this file must not do — it has no backtest behind it, and a
threshold searched for on history would make the output look validated when it
is not.
"""


@dataclass(frozen=True, slots=True)
class Signal:
    """One indicator's opinion, and the sentence explaining it."""

    name: str
    verdict: Decision
    because: str


def _trend_signal(reading: indicators.Reading) -> Signal:
    if reading.averages_stacked_up:
        return Signal("moving averages", Decision.LONG, "20 > 50 > 200, stacked up")
    if reading.averages_stacked_down:
        return Signal("moving averages", Decision.SHORT, "20 < 50 < 200, stacked down")
    return Signal("moving averages", Decision.FLAT, "not stacked, no clear direction")


def _rsi_signal(reading: indicators.Reading) -> Signal:
    value = reading.rsi
    if value >= indicators.RSI_OVERBOUGHT:
        return Signal("RSI", Decision.SHORT, f"{value:.0f}, overbought above 70")
    if value <= indicators.RSI_OVERSOLD:
        return Signal("RSI", Decision.LONG, f"{value:.0f}, oversold below 30")
    side = "upper" if value > indicators.RSI_MIDPOINT else "lower"
    return Signal("RSI", Decision.FLAT, f"{value:.0f}, mid range ({side} half)")


def _macd_signal(reading: indicators.Reading) -> Signal:
    histogram = reading.macd.histogram_bps
    if histogram > 0:
        return Signal("MACD", Decision.LONG, f"line above signal by {histogram:.1f} bps")
    if histogram < 0:
        return Signal("MACD", Decision.SHORT, f"line below signal by {-histogram:.1f} bps")
    return Signal("MACD", Decision.FLAT, "line on the signal")


def _bollinger_signal(reading: indicators.Reading) -> Signal:
    position = reading.bollinger.position
    if position >= 1:
        return Signal("Bollinger", Decision.SHORT, "price at or above the upper band")
    if position <= 0:
        return Signal("Bollinger", Decision.LONG, "price at or below the lower band")
    return Signal("Bollinger", Decision.FLAT, f"price {position:.0%} of the way up the band")


def _regime_signal(features: FeatureSet) -> Signal:
    if features.trend_regime is TrendRegime.UP:
        return Signal("regime", Decision.LONG, "trending up")
    if features.trend_regime is TrendRegime.DOWN:
        return Signal("regime", Decision.SHORT, "trending down")
    return Signal("regime", Decision.FLAT, "ranging, no trend to follow")


def signals(features: FeatureSet, reading: indicators.Reading) -> list[Signal]:
    """Five opinions, each from a different reading of the same chart.

    Deliberately not weighted. A weighting is a set of parameters, parameters
    have to be fitted, and fitting them here — with no backtest behind this
    file — would dress a guess up as a model.
    """
    return [
        _trend_signal(reading),
        _regime_signal(features),
        _macd_signal(reading),
        _rsi_signal(reading),
        _bollinger_signal(reading),
    ]


def verdict(opinions: list[Signal]) -> tuple[Decision, str]:
    """LONG, SHORT or WAIT, from how many of the five agree."""
    longs = sum(1 for opinion in opinions if opinion.verdict is Decision.LONG)
    shorts = sum(1 for opinion in opinions if opinion.verdict is Decision.SHORT)
    if longs >= AGREEMENT_FOR_ENTRY and longs > shorts:
        return Decision.LONG, f"{longs} of {len(opinions)} say long"
    if shorts >= AGREEMENT_FOR_ENTRY and shorts > longs:
        return Decision.SHORT, f"{shorts} of {len(opinions)} say short"
    return (
        Decision.FLAT,
        f"{longs} long, {shorts} short, "
        f"{len(opinions) - longs - shorts} neutral — no {AGREEMENT_FOR_ENTRY}-way agreement",
    )


ARROWS: Final = {Decision.LONG: "^ LONG ", Decision.SHORT: "v SHORT", Decision.FLAT: "- wait "}

CENTS_ABOVE: Final = Decimal(10)
"""Above this price two decimals are enough; below it they are not."""


def money(value: Decimal) -> str:
    """A price at the precision a person reads, not the precision Decimal keeps.

    Two decimals above ten, four below, because the same function prints BTC
    at 60,000 and an asset at 0.42 and rounding the second to two decimals
    would throw away most of it.
    """
    places = Decimal("0.01") if abs(value) >= CENTS_ABOVE else Decimal("0.0001")
    return f"{value.quantize(places):,}"


def render(
    *,
    asset: str,
    interval: str,
    moment: datetime,
    features: FeatureSet,
    reading: indicators.Reading,
) -> None:
    opinions = signals(features, reading)
    decision, why = verdict(opinions)

    print(f"{asset}  {interval} candle closed {moment:%Y-%m-%d %H:%M} UTC")
    print(f"price {money(reading.price)}")
    print()
    print("  indicator          says     because")
    for opinion in opinions:
        print(f"  {opinion.name:<18} {ARROWS[opinion.verdict]}  {opinion.because}")
    print()
    print(f"  DECISION: {decision.value}  ({why})")
    print()
    print("  the chart, in numbers you can check:")
    for period in indicators.MOVING_AVERAGES:
        distance = reading.distance_to_average_bps(period)
        print(
            f"    SMA{period:<4} {money(reading.averages[period]):>12}   "
            f"price {distance / 100:+.2f}% from it"
        )
    band = reading.bollinger
    print(
        f"    Bollinger  {band.lower:.2f} .. {band.upper:.2f}  (width {band.width_bps / 100:.2f}%)"
    )
    print(
        f"    ATR        {features.atr_bps / 100:.2f}% per candle, "
        f"volatility {features.volatility_regime.value}"
    )
    print(f"    support    {features.swing_low_bps / 100:.2f}% below")
    print(f"    resistance {features.swing_high_bps / 100:.2f}% above")
    print()
    print("  NOT VALIDATED. This agreement count has never been backtested.")
    print("  The trend family that was tested returned NO_EDGE_FOUND over six")
    print("  years and four assets. Read this as a summary of the chart, not as")
    print("  a recommendation, and do not put money behind it.")


def main() -> int:
    import argparse  # noqa: PLC0415 - CLI-local

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="SOL")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--venue", default="binance", choices=["hyperliquid", "binance"])
    parser.add_argument("--days", type=int, default=120)
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
    needed = max(config.warmup, indicators.warmup_needed())
    if len(candles) < needed:
        print(
            f"only {len(candles)} {request.interval} candles stored for "
            f"{request.asset} and {needed} are needed. Run "
            f"`make history ASSET={request.asset} INTERVAL={request.interval} "
            f"SOURCE={args.venue}` first."
        )
        return 1

    render(
        asset=request.asset,
        interval=request.interval,
        moment=candles[-1].close_time,
        features=compute(candles, config),
        reading=indicators.read([candle.close for candle in candles]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

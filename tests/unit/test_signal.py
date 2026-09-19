"""The live decision: what the bot says now, and why.

The verdict logic is small on purpose, and these tests hold it to the two
things that matter: it must say WAIT unless enough independent readings agree,
and it must never claim a direction its own indicators did not support.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from services.strategy_engine import indicators
from services.strategy_engine.decisions import Decision
from services.strategy_engine.features import FeatureSet, TrendRegime, VolatilityRegime
from services.strategy_engine.signal_cli import (
    AGREEMENT_FOR_ENTRY,
    Signal,
    money,
    render,
    signals,
    verdict,
)


def opinion(side: Decision) -> Signal:
    return Signal("test", side, "because")


def reading(*, closes: list[Decimal]) -> indicators.Reading:
    return indicators.read(closes)


def ramp(count: int, *, start: str = "100", step: str = "1") -> list[Decimal]:
    price = Decimal(start)
    series = []
    for _ in range(count):
        series.append(price)
        price += Decimal(step)
    return series


def features(*, trend: TrendRegime) -> FeatureSet:
    return FeatureSet(
        moment=datetime(2026, 9, 19, tzinfo=UTC),
        close=Decimal(200),
        trend_bps=Decimal(50),
        trend_slope_bps=Decimal(5),
        distance_from_trend_bps=Decimal(20),
        momentum_bps=Decimal(30),
        momentum_acceleration_bps=Decimal(2),
        atr_bps=Decimal(120),
        realized_volatility_bps=Decimal(100),
        volatility_ratio=Decimal(1),
        relative_volume=Decimal(1),
        swing_high_bps=Decimal(150),
        swing_low_bps=Decimal(200),
        trend_regime=trend,
        volatility_regime=VolatilityRegime.NORMAL,
    )


class TestVerdict:
    def test_a_majority_agreeing_gives_that_direction(self) -> None:
        decision, why = verdict([opinion(Decision.LONG)] * AGREEMENT_FOR_ENTRY)
        assert decision is Decision.LONG
        assert "say long" in why

    def test_one_short_of_the_threshold_waits(self) -> None:
        """WAIT is the default, and Phase 1 §1 makes it a real answer."""
        decision, _ = verdict([opinion(Decision.LONG)] * (AGREEMENT_FOR_ENTRY - 1))
        assert decision is Decision.FLAT

    def test_a_tie_waits(self) -> None:
        both = [opinion(Decision.LONG)] * 3 + [opinion(Decision.SHORT)] * 3
        assert verdict(both)[0] is Decision.FLAT

    def test_all_neutral_waits(self) -> None:
        decision, why = verdict([opinion(Decision.FLAT)] * 5)
        assert decision is Decision.FLAT
        assert "no" in why

    def test_the_verdict_never_invents_a_side(self) -> None:
        """Whatever the mix, the answer is one the indicators actually gave."""
        for longs in range(6):
            for shorts in range(6 - longs):
                mix = (
                    [opinion(Decision.LONG)] * longs
                    + [opinion(Decision.SHORT)] * shorts
                    + [opinion(Decision.FLAT)] * (5 - longs - shorts)
                )
                decision, _ = verdict(mix)
                if decision is Decision.LONG:
                    assert longs >= AGREEMENT_FOR_ENTRY and longs > shorts
                if decision is Decision.SHORT:
                    assert shorts >= AGREEMENT_FOR_ENTRY and shorts > longs


class TestSignals:
    def test_an_uptrend_produces_long_opinions(self) -> None:
        opinions = signals(features(trend=TrendRegime.UP), reading(closes=ramp(400)))
        sides = {item.name: item.verdict for item in opinions}
        assert sides["moving averages"] is Decision.LONG
        assert sides["regime"] is Decision.LONG

    def test_a_downtrend_produces_short_opinions(self) -> None:
        opinions = signals(
            features(trend=TrendRegime.DOWN), reading(closes=ramp(400, start="1000", step="-2"))
        )
        sides = {item.name: item.verdict for item in opinions}
        assert sides["moving averages"] is Decision.SHORT
        assert sides["regime"] is Decision.SHORT

    def test_a_range_produces_no_trend_opinion(self) -> None:
        opinions = signals(features(trend=TrendRegime.RANGE), reading(closes=[Decimal(100)] * 400))
        sides = {item.name: item.verdict for item in opinions}
        assert sides["regime"] is Decision.FLAT
        assert sides["moving averages"] is Decision.FLAT

    def test_every_opinion_carries_a_reason(self) -> None:
        """A verdict without a reason is a number nobody can check."""
        for item in signals(features(trend=TrendRegime.UP), reading(closes=ramp(400))):
            assert item.because
            assert item.name


class TestRender:
    def test_the_unvalidated_warning_is_always_printed(self, capsys: object) -> None:
        """The output must never look like a recommendation.

        This file has no backtest behind it and the tested family returned
        NO_EDGE_FOUND, so the caveat is part of the product rather than a note.
        """
        render(
            asset="SOL",
            interval="4h",
            moment=datetime(2026, 9, 19, tzinfo=UTC),
            features=features(trend=TrendRegime.UP),
            reading=reading(closes=ramp(400)),
        )
        printed = capsys.readouterr().out  # type: ignore[attr-defined]
        assert "NOT VALIDATED" in printed
        assert "NO_EDGE_FOUND" in printed

    def test_it_prints_a_decision_and_the_numbers_behind_it(self, capsys: object) -> None:
        render(
            asset="BTC",
            interval="4h",
            moment=datetime(2026, 9, 19, tzinfo=UTC),
            features=features(trend=TrendRegime.UP),
            reading=reading(closes=ramp(400, start="60000", step="50")),
        )
        printed = capsys.readouterr().out  # type: ignore[attr-defined]
        assert "DECISION:" in printed
        for period in indicators.MOVING_AVERAGES:
            assert f"SMA{period}" in printed
        assert "support" in printed
        assert "resistance" in printed


class TestMoney:
    def test_a_large_price_gets_two_decimals(self) -> None:
        assert money(Decimal("60123.456789")) == "60,123.46"

    def test_a_small_price_keeps_four(self) -> None:
        """Two decimals would throw away most of an asset priced under a dollar."""
        assert money(Decimal("0.4212345")) == "0.4212"

"""The backtest engine, and the ways a backtester flatters a strategy.

Rev.2 §26 opens the Baseline Strategy Gate with point-in-time correctness and
lookahead checks. Most of these tests are about the specific mechanisms by
which a backtest reports an edge that does not exist: filling at mid, filling
instantly, charging the spread once or three times, or collapsing gross into
net.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from services.research.backtest import (
    BacktestEngine,
    Intent,
    Quote,
    Side,
)
from services.research.costs import CostModel

START = datetime(2026, 9, 15, 4, 0, tzinfo=UTC)
LATENCY = timedelta(milliseconds=322)
FREE = CostModel(taker_fee_bps=Decimal(0), half_spread_bps=Decimal(0))


def quote(offset_ms: int, bid: str = "59999.5", ask: str = "60000.5") -> Quote:
    return Quote(
        moment=START + timedelta(milliseconds=offset_ms),
        bid=Decimal(bid),
        ask=Decimal(ask),
    )


class OnceAt:
    """Buys on the first quote, sells on the one at `exit_after_ms`."""

    name = "once"

    def __init__(self, exit_after_ms: int) -> None:
        self.exit_after_ms = exit_after_ms
        self.bought = False
        self.sold = False

    def on_event(self, q: Quote) -> Intent | None:
        elapsed = (q.moment - START).total_seconds() * 1000
        if not self.bought:
            self.bought = True
            return Intent(side=Side.BUY, quantity=Decimal(1))
        if not self.sold and elapsed >= self.exit_after_ms:
            self.sold = True
            return Intent(side=Side.SELL, quantity=Decimal(1))
        return None


class Never:
    name = "never"

    def on_event(self, q: Quote) -> Intent | None:  # noqa: ARG002
        return None


class TestExecutionTiming:
    def test_a_decision_cannot_fill_on_the_quote_that_caused_it(self) -> None:
        """Instant fills are the purest form of lookahead."""
        quotes = [quote(0), quote(1000, "60099.5", "60100.5")]
        result = BacktestEngine(strategy=OnceAt(999_999), costs=FREE).run(quotes)
        assert result.intents_formed == 1
        # The entry filled on the later quote, not the one it was decided on.
        assert result.intents_unfilled == 1  # still open at the end
        assert result.trades == ()

    def test_the_fill_waits_for_the_latency_to_elapse(self) -> None:
        """A quote 100 ms later cannot fill a decision that needs 322 ms."""
        quotes = [quote(0), quote(100), quote(400, "60099.5", "60100.5"), quote(500)]
        engine = BacktestEngine(strategy=OnceAt(999_999), costs=FREE, latency=LATENCY)
        result = engine.run(quotes)
        assert result.trades == ()
        assert result.intents_unfilled == 1

    def test_the_fill_price_is_the_market_at_execution_not_at_decision(self) -> None:
        """The whole point: nobody fills at the price they saw."""
        quotes = [quote(0), quote(400, "60099.5", "60100.5"), quote(2000, "60099.5", "60100.5")]
        engine = BacktestEngine(strategy=OnceAt(400), costs=FREE, latency=LATENCY)
        result = engine.run(quotes)
        assert len(result.trades) == 1
        entry = result.trades[0].entry
        assert entry.decision_price == Decimal("60000.5")
        assert entry.fill_price == Decimal("60100.5")

    def test_out_of_order_quotes_are_refused(self) -> None:
        """Otherwise a backtest can fill before it decided."""
        with pytest.raises(ValueError, match="not in time order"):
            BacktestEngine(strategy=Never()).run([quote(100), quote(0)])


class TestFillPricing:
    def test_a_buy_lifts_the_ask_and_a_sell_hits_the_bid(self) -> None:
        """Filling at mid invents half a spread on every side of every trade."""
        assert quote(0).touch(Side.BUY) == Decimal("60000.5")
        assert quote(0).touch(Side.SELL) == Decimal("59999.5")
        assert quote(0).mid == Decimal(60000)

    def test_a_flat_market_round_trip_loses_the_spread(self) -> None:
        """Buy the ask, sell the bid, unchanged market: the spread is the loss.

        With fees zeroed this isolates the spread, and it must be exactly one
        spread — not half, not two.
        """
        quotes = [quote(0), quote(400), quote(1000), quote(2000)]
        engine = BacktestEngine(strategy=OnceAt(400), costs=FREE, latency=LATENCY)
        result = engine.run(quotes)
        assert len(result.trades) == 1
        assert result.trades[0].gross_pnl == Decimal(-1)

    def test_the_spread_is_not_charged_twice(self) -> None:
        """The fill is at the touch, so half_spread_bps must not apply again.

        A cost model with a large half-spread must produce the same result as
        one without, because the backtester never uses that field.
        """
        quotes = [quote(0), quote(400), quote(1000), quote(2000)]
        wide = CostModel(taker_fee_bps=Decimal(0), half_spread_bps=Decimal(50))
        plain = BacktestEngine(strategy=OnceAt(400), costs=FREE, latency=LATENCY).run(quotes)
        widened = BacktestEngine(strategy=OnceAt(400), costs=wide, latency=LATENCY).run(quotes)
        assert plain.net_pnl == widened.net_pnl

    def test_the_fee_is_charged_on_both_sides(self) -> None:
        quotes = [quote(0), quote(400), quote(1000), quote(2000)]
        model = CostModel(taker_fee_bps=Decimal("4.5"), half_spread_bps=Decimal(0))
        result = BacktestEngine(strategy=OnceAt(400), costs=model, latency=LATENCY).run(quotes)
        trade = result.trades[0]
        assert trade.entry.fee > 0
        assert trade.exit.fee > 0
        assert trade.fees == trade.entry.fee + trade.exit.fee


class TestAdverseDrift:
    def test_a_fill_worse_than_the_decision_is_positive_slippage(self) -> None:
        """Bought at 60000.5, filled at 60100.5: the market moved away."""
        quotes = [quote(0), quote(400, "60099.5", "60100.5"), quote(2000, "60099.5", "60100.5")]
        result = BacktestEngine(strategy=OnceAt(400), costs=FREE, latency=LATENCY).run(quotes)
        assert result.trades[0].entry.slippage_bps > 0

    def test_a_fill_better_than_the_decision_is_negative_slippage(self) -> None:
        """Latency is not always a cost, and a model that assumed so would lie."""
        quotes = [quote(0), quote(400, "59899.5", "59900.5"), quote(2000, "59899.5", "59900.5")]
        result = BacktestEngine(strategy=OnceAt(400), costs=FREE, latency=LATENCY).run(quotes)
        assert result.trades[0].entry.slippage_bps < 0

    def test_drift_is_measured_not_assumed(self) -> None:
        """`measure.py` refused to guess this; here it comes out of the run."""
        quotes = [quote(0), quote(400, "60099.5", "60100.5"), quote(2000, "60099.5", "60100.5")]
        result = BacktestEngine(strategy=OnceAt(400), costs=FREE, latency=LATENCY).run(quotes)
        assert result.mean_adverse_drift_bps is not None

    def test_no_trades_means_no_average(self) -> None:
        """An average over nothing is not zero."""
        result = BacktestEngine(strategy=Never()).run([quote(0), quote(400)])
        assert result.mean_adverse_drift_bps is None


class TestHonestReporting:
    def test_gross_and_net_are_both_kept(self) -> None:
        """§25's finding is only visible if the two are never collapsed."""
        quotes = [quote(0), quote(400, "60049.5", "60050.5"), quote(2000, "60049.5", "60050.5")]
        model = CostModel(taker_fee_bps=Decimal("4.5"), half_spread_bps=Decimal(0))
        result = BacktestEngine(strategy=OnceAt(400), costs=model, latency=LATENCY).run(quotes)
        assert result.gross_pnl != result.net_pnl
        assert result.fees > 0

    def test_a_profitable_gross_and_losing_net_is_flagged(self) -> None:
        """The exact case §25 names: costs ate the edge.

        The move has to clear the spread and fall short of the fee, which is
        the whole band this project is trying to find out whether anything
        occupies. Buy at 60000.5, sell at 60009.5: +9 gross, against about 54
        of fee on a 60,000 round trip at 4.5 bps a side.
        """
        quotes = [quote(0), quote(400), quote(2000, "60009.5", "60010.5")]
        model = CostModel(taker_fee_bps=Decimal("4.5"), half_spread_bps=Decimal(0))
        result = BacktestEngine(strategy=OnceAt(400), costs=model, latency=LATENCY).run(quotes)
        assert result.gross_pnl == Decimal(9)
        assert result.net_pnl < 0
        assert result.costs_exceeded_edge is True

    def test_no_trades_makes_the_verdict_unknown_not_false(self) -> None:
        """A strategy that never traded has demonstrated neither."""
        result = BacktestEngine(strategy=Never()).run([quote(0), quote(400)])
        assert result.costs_exceeded_edge is None

    def test_unfilled_intents_are_counted(self) -> None:
        """A strategy whose intents expire is not its trade list."""
        result = BacktestEngine(strategy=OnceAt(999_999), costs=FREE).run([quote(0), quote(400)])
        assert result.intents_formed == 1
        assert result.intents_unfilled == 1

    def test_the_summary_states_the_latency_it_assumed(self) -> None:
        """A P&L without its latency assumption cannot be compared or disputed."""
        result = BacktestEngine(strategy=Never(), latency=LATENCY).run([quote(0)])
        assert result.summary()["latency_ms"] == 322.0


class TestIntentValidation:
    def test_a_non_positive_quantity_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            Intent(side=Side.BUY, quantity=Decimal(0))

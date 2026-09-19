"""The first strategy, and the properties that make its result mean anything.

Most of these are not about whether it makes money. They are about whether a
number it produces could be trusted if it did — a strategy that can see the
future, or a filter that is not filtering, produces a figure that is worse than
no figure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from services.research.backtest import BacktestEngine, Quote, Side
from services.research.costs import CostModel
from services.strategy_engine.baseline import (
    AlwaysFlatStrategy,
    BaselineStrategy,
    BookOnlyStrategy,
    FlowWindow,
)
from services.strategy_engine.stream import StreamError, quotes_from_rows

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


def quote(
    second: float,
    *,
    bid: str = "100",
    ask: str = "100.10",
    bid_size: str | None = "1",
    ask_size: str | None = "1",
    flow: str | None = None,
) -> Quote:
    return Quote(
        moment=NOW + timedelta(seconds=second),
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=None if bid_size is None else Decimal(bid_size),
        ask_size=None if ask_size is None else Decimal(ask_size),
        flow=None if flow is None else Decimal(flow),
    )


class TestBookImbalance:
    def test_a_balanced_book_is_zero(self) -> None:
        assert quote(0).book_imbalance == 0

    def test_all_size_on_the_bid_is_one(self) -> None:
        assert quote(0, bid_size="5", ask_size="0").book_imbalance == 1

    def test_a_missing_side_has_no_imbalance(self) -> None:
        """A missing book is not a balanced one, and must not read as zero."""
        assert quote(0, bid_size=None).book_imbalance is None

    def test_an_empty_book_has_no_imbalance(self) -> None:
        assert quote(0, bid_size="0", ask_size="0").book_imbalance is None


class TestFlowWindow:
    def test_flow_inside_the_window_accumulates(self) -> None:
        window = FlowWindow(window=timedelta(seconds=10))
        window.observe(NOW, Decimal(2))
        window.observe(NOW + timedelta(seconds=5), Decimal(3))
        assert window.value(NOW + timedelta(seconds=5)) == 5

    def test_flow_older_than_the_window_leaves(self) -> None:
        window = FlowWindow(window=timedelta(seconds=10))
        window.observe(NOW, Decimal(2))
        assert window.value(NOW + timedelta(seconds=11)) == 0

    def test_the_edge_is_exact_rather_than_decayed(self) -> None:
        """A decay would make "the last ten seconds" mean something different each call."""
        window = FlowWindow(window=timedelta(seconds=10))
        window.observe(NOW, Decimal(2))
        assert window.value(NOW + timedelta(seconds=9, milliseconds=999)) == 2
        assert window.value(NOW + timedelta(seconds=10, milliseconds=1)) == 0


class TestEntryRequiresAgreement:
    def strategy(self, **overrides: Any) -> BaselineStrategy:
        base: dict[str, Any] = {"threshold": Decimal("0.30"), "hold": timedelta(seconds=30)}
        base.update(overrides)
        return BaselineStrategy(**base)

    def test_imbalance_and_flow_pointing_the_same_way_enters(self) -> None:
        strategy = self.strategy()
        intent = strategy.on_event(quote(0, bid_size="4", ask_size="1", flow="5"))
        assert intent is not None
        assert intent.side is Side.BUY

    def test_imbalance_without_flow_does_not_enter(self) -> None:
        """The filter has to actually filter, or it is decoration."""
        strategy = self.strategy()
        assert strategy.on_event(quote(0, bid_size="4", ask_size="1", flow="0")) is None

    def test_flow_against_the_book_does_not_enter(self) -> None:
        strategy = self.strategy()
        assert strategy.on_event(quote(0, bid_size="4", ask_size="1", flow="-5")) is None

    def test_a_window_with_no_trades_is_not_confirmation(self) -> None:
        """Silence agrees with nothing. Treating it as assent disables the filter."""
        strategy = self.strategy()
        assert strategy.on_event(quote(0, bid_size="4", ask_size="1", flow=None)) is None

    def test_an_imbalance_below_the_threshold_does_not_enter(self) -> None:
        strategy = self.strategy()
        assert strategy.on_event(quote(0, bid_size="11", ask_size="10", flow="5")) is None

    def test_the_short_side_is_symmetric(self) -> None:
        strategy = self.strategy()
        intent = strategy.on_event(quote(0, bid_size="1", ask_size="4", flow="-5"))
        assert intent is not None
        assert intent.side is Side.SELL

    def test_no_depth_means_no_signal(self) -> None:
        strategy = self.strategy()
        assert strategy.on_event(quote(0, bid_size=None, flow="5")) is None


class TestHolding:
    def test_only_one_position_is_held_at_a_time(self) -> None:
        strategy = BaselineStrategy(hold=timedelta(seconds=30))
        assert strategy.on_event(quote(0, bid_size="4", ask_size="1", flow="5")) is not None
        assert strategy.on_event(quote(1, bid_size="9", ask_size="1", flow="9")) is None

    def test_the_position_closes_when_the_hold_elapses(self) -> None:
        strategy = BaselineStrategy(hold=timedelta(seconds=30))
        strategy.on_event(quote(0, bid_size="4", ask_size="1", flow="5"))
        assert strategy.on_event(quote(29, bid_size="4", ask_size="1", flow="5")) is None
        closing = strategy.on_event(quote(30, bid_size="4", ask_size="1", flow="5"))
        assert closing is not None
        assert closing.side is Side.SELL
        assert closing.reason == "hold elapsed"

    def test_it_can_enter_again_after_closing(self) -> None:
        strategy = BaselineStrategy(hold=timedelta(seconds=10))
        strategy.on_event(quote(0, bid_size="4", ask_size="1", flow="5"))
        strategy.on_event(quote(10, bid_size="4", ask_size="1", flow="5"))
        assert strategy.on_event(quote(11, bid_size="4", ask_size="1", flow="5")) is not None

    def test_a_closing_intent_is_the_opposite_side(self) -> None:
        strategy = BaselineStrategy(hold=timedelta(seconds=5))
        strategy.on_event(quote(0, bid_size="1", ask_size="4", flow="-5"))
        closing = strategy.on_event(quote(5, bid_size="1", ask_size="4", flow="-5"))
        assert closing is not None
        assert closing.side is Side.BUY


class TestRefusedParameters:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("threshold", Decimal(0)),
            ("threshold", Decimal("1.5")),
            ("hold", timedelta(0)),
            ("quantity", Decimal(0)),
        ],
    )
    def test_a_parameter_outside_its_range_is_refused(self, field: str, value: Any) -> None:
        with pytest.raises(ValueError, match="must be"):
            BaselineStrategy(**{field: value})


class TestControlAndComparison:
    """The two runs that make a third run interpretable."""

    def test_the_control_never_trades(self) -> None:
        control = AlwaysFlatStrategy()
        for second in range(100):
            assert control.on_event(quote(second, bid_size="9", ask_size="1", flow="9")) is None

    def test_the_control_earns_exactly_zero_through_the_engine(self) -> None:
        """A harness that pays the control anything is a harness to distrust."""
        engine = BacktestEngine(strategy=AlwaysFlatStrategy(), costs=CostModel())
        result = engine.run([quote(i) for i in range(50)])
        assert result.trades == ()
        assert result.net_pnl == 0
        assert result.gross_pnl == 0

    def test_the_book_only_variant_ignores_flow(self) -> None:
        """It exists to be the thing the filter is measured against."""
        book_only = BookOnlyStrategy(threshold=Decimal("0.30"))
        assert book_only.on_event(quote(0, bid_size="4", ask_size="1", flow="-9")) is not None

    def test_removing_the_filter_can_only_add_entries(self) -> None:
        events = [
            quote(i, bid_size="4", ask_size="1", flow="-1" if i % 2 else "1")
            for i in range(0, 300, 3)
        ]
        both = BaselineStrategy(hold=timedelta(seconds=1))
        book = BookOnlyStrategy(hold=timedelta(seconds=1))
        for event in events:
            both.on_event(event)
            book.on_event(event)
        assert book.agreements >= both.agreements


class TestStreamHasNoLookahead:
    """The smallest lookahead available here, and the one that would not show up.

    Attributing a trade to the quote *before* it would let a strategy see, at
    the moment of a quote, aggression that had not happened yet. It would raise
    the backtest's return and leave no trace in the output.
    """

    def row(self, second: float, event_type: str, **fields: Any) -> dict[str, Any]:
        return {
            "event_type": event_type,
            "local_receive_time": NOW + timedelta(seconds=second),
            **fields,
        }

    def test_a_trade_is_folded_into_the_next_quote_not_the_previous(self) -> None:
        rows = [
            self.row(0, "BBO", bid_price=Decimal(100), ask_price=Decimal("100.1")),
            self.row(1, "TRADE", quantity=Decimal(5), side="BUY"),
            self.row(2, "BBO", bid_price=Decimal(100), ask_price=Decimal("100.1")),
        ]
        first, second = list(quotes_from_rows(rows))
        assert first.flow is None
        assert second.flow == 5

    def test_flow_is_signed_by_the_aggressor(self) -> None:
        rows = [
            self.row(1, "TRADE", quantity=Decimal(3), side="SELL"),
            self.row(2, "BBO", bid_price=Decimal(100), ask_price=Decimal("100.1")),
        ]
        (only,) = list(quotes_from_rows(rows))
        assert only.flow == -3

    def test_flow_resets_after_each_quote(self) -> None:
        rows = [
            self.row(1, "TRADE", quantity=Decimal(3), side="BUY"),
            self.row(2, "BBO", bid_price=Decimal(100), ask_price=Decimal("100.1")),
            self.row(3, "BBO", bid_price=Decimal(100), ask_price=Decimal("100.1")),
        ]
        first, second = list(quotes_from_rows(rows))
        assert first.flow == 3
        assert second.flow is None

    def test_an_unsigned_trade_is_dropped_rather_than_counted_as_zero(self) -> None:
        rows = [
            self.row(1, "TRADE", quantity=Decimal(3), side=None),
            self.row(2, "BBO", bid_price=Decimal(100), ask_price=Decimal("100.1")),
        ]
        (only,) = list(quotes_from_rows(rows))
        assert only.flow is None

    def test_a_crossed_book_is_skipped_rather_than_traded(self) -> None:
        rows = [self.row(0, "BBO", bid_price=Decimal(101), ask_price=Decimal(100))]
        assert list(quotes_from_rows(rows)) == []

    def test_l2_snapshots_are_not_treated_as_quotes(self) -> None:
        """Two views of one moment must not enter the series as two moments."""
        rows = [
            self.row(0, "L2_SNAPSHOT", bid_price=Decimal(100), ask_price=Decimal("100.1")),
            self.row(1, "BBO", bid_price=Decimal(100), ask_price=Decimal("100.1")),
        ]
        assert len(list(quotes_from_rows(rows))) == 1

    def test_rows_out_of_receipt_order_are_refused(self) -> None:
        rows = [
            self.row(5, "BBO", bid_price=Decimal(100), ask_price=Decimal("100.1")),
            self.row(1, "BBO", bid_price=Decimal(100), ask_price=Decimal("100.1")),
        ]
        with pytest.raises(StreamError, match="receipt order"):
            list(quotes_from_rows(rows))


class TestEndToEnd:
    def test_a_full_run_produces_trades_and_charges_them(self) -> None:
        # A rising market with the book and flow both leaning long.
        quotes = [
            quote(
                i,
                bid=str(100 + i * Decimal("0.01")),
                ask=str(100 + i * Decimal("0.01") + Decimal("0.10")),
                bid_size="4",
                ask_size="1",
                flow="5",
            )
            for i in range(0, 200)
        ]
        engine = BacktestEngine(
            strategy=BaselineStrategy(hold=timedelta(seconds=30)),
            costs=CostModel(half_spread_bps=Decimal("0.4924")),
            latency=timedelta(milliseconds=322),
        )
        result = engine.run(quotes)
        assert result.trades
        assert result.fees > 0
        # Fills happen after the decision, never on the quote that caused it.
        for trade in result.trades:
            assert trade.entry.filled_at > trade.entry.decided_at

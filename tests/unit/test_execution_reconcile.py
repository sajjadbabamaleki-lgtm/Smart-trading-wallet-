"""Reconciliation, and the difference between "not yet" and "impossible".

Invariant 8 makes the venue authoritative and calls an unexplained mismatch a
critical event. The work here is deciding which mismatches are unexplained: an
order the venue has not listed a moment after we sent it is ordinary, an order
the venue has that we never sent is not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from libs.exchange.models import OrderState, OrderStatus, Position
from libs.schemas.enums import Side
from services.execution_engine import (
    DiscrepancyKind,
    OrderRecord,
    ReconciliationReport,
    Severity,
    believed_positions,
    reconcile,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def record(state: OrderState, *, filled: Decimal = Decimal(0)) -> OrderRecord:
    return OrderRecord(
        client_order_id="stw-1",
        intent_id="int_1",
        correlation_id="cor_1",
        asset="BTC",
        quantity=Decimal("0.001"),
        state=state,
        filled_quantity=filled,
    )


def status(
    state: OrderState,
    *,
    client_order_id: str = "stw-1",
    filled: Decimal = Decimal(0),
) -> OrderStatus:
    return OrderStatus(
        client_order_id=client_order_id,
        state=state,
        filled_quantity=filled,
        observed_at=NOW,
    )


def run(
    records: dict[str, OrderRecord] | None = None,
    venue_orders: tuple[OrderStatus, ...] = (),
    believed: dict[str, Decimal] | None = None,
    venue_positions: tuple[Position, ...] = (),
) -> ReconciliationReport:
    return reconcile(
        records=records or {},
        venue_orders=venue_orders,
        believed=believed or {},
        venue_positions=venue_positions,
    )


class TestAgreement:
    def test_two_matching_views_are_clean(self) -> None:
        report = run(
            records={"stw-1": record(OrderState.FILLED, filled=Decimal("0.001"))},
            venue_orders=(status(OrderState.FILLED, filled=Decimal("0.001")),),
            believed={"BTC": Decimal("0.001")},
            venue_positions=(Position(asset="BTC", size=Decimal("0.001")),),
        )
        assert report.is_clean
        assert report.new_exposure_permitted

    def test_a_terminal_order_the_venue_no_longer_lists_is_fine(self) -> None:
        """Venues drop completed orders from their open list."""
        report = run(records={"stw-1": record(OrderState.FILLED, filled=Decimal("0.001"))})
        assert report.is_clean


class TestUnresolved:
    def test_an_order_just_submitted_and_not_yet_listed_is_not_an_alarm(self) -> None:
        report = run(records={"stw-1": record(OrderState.SUBMITTED)})
        assert report.critical == ()
        assert report.unresolved[0].kind is DiscrepancyKind.ORDER_MISSING_AT_VENUE

    def test_unresolved_still_blocks_new_exposure(self) -> None:
        """Invariant 7: not knowing is not permission."""
        report = run(records={"stw-1": record(OrderState.UNKNOWN)})
        assert not report.new_exposure_permitted

    def test_a_lagging_state_resolves_by_adopting_the_venue(self) -> None:
        report = run(
            records={"stw-1": record(OrderState.ACKNOWLEDGED)},
            venue_orders=(status(OrderState.FILLED, filled=Decimal("0.001")),),
        )
        kinds = {d.kind for d in report.discrepancies}
        assert kinds == {
            DiscrepancyKind.ORDER_STATE_DIFFERS,
            DiscrepancyKind.FILL_QUANTITY_DIFFERS,
        }
        assert all(d.severity is Severity.INFO for d in report.discrepancies)


class TestCritical:
    def test_an_order_we_never_sent_stops_trading(self) -> None:
        report = run(venue_orders=(status(OrderState.ACKNOWLEDGED, client_order_id="x-9"),))
        assert report.critical[0].kind is DiscrepancyKind.ORDER_UNKNOWN_TO_US
        assert not report.new_exposure_permitted

    def test_an_acknowledged_order_that_vanished_is_critical(self) -> None:
        """The venue told us it existed; now it denies it."""
        report = run(records={"stw-1": record(OrderState.ACKNOWLEDGED)})
        assert report.critical[0].kind is DiscrepancyKind.ORDER_MISSING_AT_VENUE

    def test_a_position_we_do_not_know_about_stops_trading(self) -> None:
        report = run(venue_positions=(Position(asset="BTC", size=Decimal("0.01")),))
        assert report.critical[0].kind is DiscrepancyKind.POSITION_UNKNOWN_TO_US

    def test_a_size_that_differs_stops_trading(self) -> None:
        report = run(
            believed={"BTC": Decimal("0.001")},
            venue_positions=(Position(asset="BTC", size=Decimal("0.002")),),
        )
        assert report.critical[0].kind is DiscrepancyKind.POSITION_SIZE_DIFFERS

    def test_exposure_we_believe_in_that_the_venue_denies_is_critical(self) -> None:
        report = run(believed={"BTC": Decimal("0.001")})
        assert report.critical[0].kind is DiscrepancyKind.POSITION_MISSING_AT_VENUE

    def test_a_flat_venue_position_is_not_a_position(self) -> None:
        report = run(venue_positions=(Position(asset="BTC", size=Decimal(0)),))
        assert report.is_clean


class TestBelief:
    def test_a_long_and_a_short_net_off(self) -> None:
        records = {
            "a": OrderRecord(
                client_order_id="a",
                intent_id="i",
                correlation_id="c",
                asset="BTC",
                quantity=Decimal("0.001"),
                filled_quantity=Decimal("0.001"),
            ),
            "b": OrderRecord(
                client_order_id="b",
                intent_id="i",
                correlation_id="c",
                asset="BTC",
                quantity=Decimal("0.001"),
                filled_quantity=Decimal("0.001"),
            ),
        }
        sides = {"a": Side.BUY, "b": Side.SELL}
        assert believed_positions(records, sides) == {}

    def test_unfilled_orders_are_not_exposure(self) -> None:
        records = {"a": record(OrderState.ACKNOWLEDGED)}
        assert believed_positions(records, {"stw-1": Side.BUY}) == {}

    def test_a_fill_whose_side_we_lost_is_not_guessed(self) -> None:
        """Assuming a direction would invent exposure in the wrong direction."""
        records = {"stw-1": record(OrderState.FILLED, filled=Decimal("0.001"))}
        assert believed_positions(records, {}) == {}

    def test_fills_accumulate_into_one_net_size(self) -> None:
        records = {
            "a": OrderRecord(
                client_order_id="a",
                intent_id="i",
                correlation_id="c",
                asset="BTC",
                quantity=Decimal("0.001"),
                filled_quantity=Decimal("0.001"),
            ),
            "b": OrderRecord(
                client_order_id="b",
                intent_id="i",
                correlation_id="c",
                asset="BTC",
                quantity=Decimal("0.002"),
                filled_quantity=Decimal("0.002"),
            ),
        }
        sides = {"a": Side.BUY, "b": Side.BUY}
        assert believed_positions(records, sides) == {"BTC": Decimal("0.003")}

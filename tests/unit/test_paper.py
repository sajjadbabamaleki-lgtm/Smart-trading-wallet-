"""Paper trading: the decision written before its outcome exists.

Tested against a fake connection rather than a database, because what matters
here is the state machine and the idempotence, not the SQL. Three properties
carry the weight:

- the same candle decided twice changes nothing, since a timer that fires
  twice must not produce two positions on one piece of information;
- a reversal closes before it opens, in one transaction, so a crash cannot
  leave the book flat while the log says it reversed;
- every decision is logged, including the ones that changed nothing, because a
  rule that has quietly stopped signalling looks identical to a rule that is
  patiently flat unless the flats are recorded.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from services.research.costs import CostModel
from services.strategy_engine.decisions import Decision
from services.strategy_engine.paper import (
    OpenPosition,
    PaperBook,
    PaperContext,
    Tick,
)

MOMENT = datetime(2026, 9, 20, 4, 0, tzinfo=UTC)
CONTEXT = PaperContext(venue="binance", asset="BTC", interval="4h", rule="funding-extreme")
NO_COST = CostModel(taker_fee_bps=Decimal(0), half_spread_bps=Decimal(0))


@dataclass
class FakeCursor:
    store: FakeConnection

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.store.statements.append((sql, params))
        if sql.startswith("SELECT 1 FROM paper_decisions"):
            self.store.result = (1,) if params[-1] in self.store.decided else None
        elif sql.startswith("SELECT position_id"):
            self.store.result = self.store.held
        elif sql.startswith("INSERT INTO paper_positions"):
            self.store.opened.append(params)
        elif sql.startswith("UPDATE paper_positions"):
            self.store.closed.append(params)
        elif sql.startswith("INSERT INTO paper_decisions"):
            self.store.logged.append(params)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.store.result


@dataclass
class FakeConnection:
    """Enough of a connection to exercise the state machine."""

    decided: set[datetime] = field(default_factory=set)
    held: tuple[Any, ...] | None = None
    result: tuple[Any, ...] | None = None
    statements: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    opened: list[tuple[Any, ...]] = field(default_factory=list)
    closed: list[tuple[Any, ...]] = field(default_factory=list)
    logged: list[tuple[Any, ...]] = field(default_factory=list)
    commits: int = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1


def book(connection: FakeConnection) -> PaperBook:
    return PaperBook(
        connection=connection,  # type: ignore[arg-type]
        context=CONTEXT,
        costs=NO_COST,
        notional=Decimal(1000),
    )


def tick(decision: Decision, *, price: str = "60000", at: datetime = MOMENT) -> Tick:
    return Tick(
        decision=decision,
        price=Decimal(price),
        candle_close=at,
        decided_at=at + timedelta(minutes=5),
        reasons={"trend_regime": "UP"},
    )


def holding(side: Decision, *, entry: str = "60000") -> tuple[Any, ...]:
    return (
        uuid.uuid4(),
        side.value,
        MOMENT - timedelta(hours=8),
        Decimal(entry),
        Decimal(1000) / Decimal(entry),
        Decimal(1000),
        Decimal(0),
    )


class TestIdempotence:
    def test_a_candle_decided_twice_changes_nothing(self) -> None:
        """A timer that fires twice must not open two positions."""
        connection = FakeConnection(decided={MOMENT})
        applied = book(connection).apply(tick(Decision.LONG))
        assert applied.recorded is False
        assert connection.opened == []
        assert connection.logged == []
        assert connection.commits == 0

    def test_a_repeat_is_not_an_error(self) -> None:
        """It is the expected case, so the caller gets a result, not a raise."""
        connection = FakeConnection(decided={MOMENT})
        assert book(connection).apply(tick(Decision.SHORT)).decision is Decision.SHORT

    def test_a_different_candle_is_a_new_decision(self) -> None:
        connection = FakeConnection(decided={MOMENT})
        later = MOMENT + timedelta(hours=4)
        assert book(connection).apply(tick(Decision.LONG, at=later)).recorded is True


class TestOpening:
    def test_a_long_from_flat_opens_one_position(self) -> None:
        connection = FakeConnection()
        applied = book(connection).apply(tick(Decision.LONG))
        assert applied.opened is not None
        assert applied.closed is None
        assert len(connection.opened) == 1

    def test_flat_from_flat_opens_nothing(self) -> None:
        connection = FakeConnection()
        applied = book(connection).apply(tick(Decision.FLAT))
        assert applied.opened is None
        assert connection.opened == []

    def test_the_quantity_matches_the_notional_at_the_price(self) -> None:
        connection = FakeConnection()
        book(connection).apply(tick(Decision.LONG, price="50000"))
        params = connection.opened[0]
        assert Decimal(1000) / Decimal(50000) in params
        assert Decimal(1000) in params


class TestHolding:
    def test_the_same_side_again_changes_nothing(self) -> None:
        """HOLD is a target equal to the position already held."""
        connection = FakeConnection(held=holding(Decision.LONG))
        applied = book(connection).apply(tick(Decision.LONG))
        assert applied.opened is None
        assert applied.closed is None
        assert connection.opened == []
        assert connection.closed == []

    def test_flat_closes_without_reopening(self) -> None:
        connection = FakeConnection(held=holding(Decision.LONG))
        applied = book(connection).apply(tick(Decision.FLAT))
        assert applied.closed is not None
        assert applied.opened is None

    def test_a_reversal_closes_then_opens(self) -> None:
        """Two fills, not one — the cost of a flip is charged twice."""
        connection = FakeConnection(held=holding(Decision.LONG))
        applied = book(connection).apply(tick(Decision.SHORT))
        assert applied.closed is not None
        assert applied.opened is not None
        assert len(connection.closed) == 1
        assert len(connection.opened) == 1

    def test_a_whole_tick_is_one_transaction(self) -> None:
        """A crash mid-reversal must not leave the book and the log disagreeing."""
        connection = FakeConnection(held=holding(Decision.LONG))
        book(connection).apply(tick(Decision.SHORT))
        assert connection.commits == 1


class TestRealised:
    def test_a_profitable_long_reports_what_it_made(self) -> None:
        connection = FakeConnection(held=holding(Decision.LONG, entry="50000"))
        applied = book(connection).apply(tick(Decision.FLAT, price="55000"))
        # 1,000 of notional at 50,000 is 0.02 units; a 5,000 move is 100.
        assert applied.realised == Decimal(100)

    def test_a_short_profits_when_price_falls(self) -> None:
        connection = FakeConnection(held=holding(Decision.SHORT, entry="50000"))
        applied = book(connection).apply(tick(Decision.FLAT, price="45000"))
        assert applied.realised == Decimal(100)

    def test_fees_are_taken_off_the_realised_figure(self) -> None:
        connection = FakeConnection(held=holding(Decision.LONG, entry="50000"))
        costed = PaperBook(
            connection=connection,  # type: ignore[arg-type]
            context=CONTEXT,
            costs=CostModel(taker_fee_bps=Decimal(10), half_spread_bps=Decimal(0)),
            notional=Decimal(1000),
        )
        applied = costed.apply(tick(Decision.FLAT, price="55000"))
        assert applied.realised is not None
        assert applied.realised < Decimal(100)


class TestLogging:
    def test_a_decision_that_changed_nothing_is_still_logged(self) -> None:
        """Otherwise a rule that stopped signalling looks like one that is flat."""
        connection = FakeConnection()
        book(connection).apply(tick(Decision.FLAT))
        assert len(connection.logged) == 1

    def test_the_reasons_are_stored_with_the_decision(self) -> None:
        """So a months-old decision can be audited without re-running features."""
        connection = FakeConnection()
        book(connection).apply(tick(Decision.LONG))
        assert any("trend_regime" in str(value) for value in connection.logged[0])

    def test_the_candle_close_and_the_run_time_are_both_kept(self) -> None:
        """A timer that fires late must not look like a later decision."""
        connection = FakeConnection()
        moment = tick(Decision.LONG)
        book(connection).apply(moment)
        stored = connection.logged[0]
        assert moment.candle_close in stored
        assert moment.decided_at in stored
        assert moment.decided_at != moment.candle_close


class TestMarking:
    def test_an_open_long_marks_up_when_price_rises(self) -> None:
        position = OpenPosition(
            position_id=uuid.uuid4(),
            side=Decision.LONG,
            opened_at=MOMENT,
            entry_price=Decimal(50000),
            quantity=Decimal("0.02"),
            notional=Decimal(1000),
            fees=Decimal(0),
        )
        assert position.unrealised(Decimal(55000)) == Decimal(100)

    def test_an_open_short_marks_up_when_price_falls(self) -> None:
        position = OpenPosition(
            position_id=uuid.uuid4(),
            side=Decision.SHORT,
            opened_at=MOMENT,
            entry_price=Decimal(50000),
            quantity=Decimal("0.02"),
            notional=Decimal(1000),
            fees=Decimal(0),
        )
        assert position.unrealised(Decimal(45000)) == Decimal(100)

    def test_fees_already_paid_are_carried_in_the_mark(self) -> None:
        position = OpenPosition(
            position_id=uuid.uuid4(),
            side=Decision.LONG,
            opened_at=MOMENT,
            entry_price=Decimal(50000),
            quantity=Decimal("0.02"),
            notional=Decimal(1000),
            fees=Decimal(5),
        )
        assert position.unrealised(Decimal(50000)) == Decimal(-5)

"""Paper trading: one decision per candle, recorded before the outcome exists.

This is the only test in the project a researcher cannot cheat. A backtest runs
against history that has already happened, and history can be searched until
something fits — eight rules have been searched against it here. Forward
testing cannot be searched, because the decision is written down before the
price that judges it exists.

**It holds no capital and reaches no venue.** Every position is a row. The
state machine is the same one `CandleBacktest` runs — a position opens when the
target leaves FLAT and closes when the target changes — so a forward result and
a backtest result are comparable rather than merely similar.

**Idempotent by design.** A timer that fires twice inside an interval, or a
manual run beside the timer, must not produce two decisions on the same
information: the database refuses a duplicate decision for a candle, and the
engine treats that refusal as "already handled" rather than an error. The same
holds for positions, where a unique index permits one open position per rule
and asset — so a crashed run that retries cannot silently double the exposure.

**Nothing here is evidence of profit.** It is evidence about a rule, gathered
in the one way that cannot be fitted, and the rule it is gathering evidence
about has already failed a backtest. That is the point: a forward record of a
rule expected to lose is how this project learns whether its backtests
generalise at all.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from services.research.costs import BPS, CostModel
from services.strategy_engine.decisions import Decision

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from psycopg import Connection

DEFAULT_NOTIONAL: Final = Decimal(1000)
"""Size of each paper position, in quote currency.

Fixed and non-compounding, exactly as in the backtester, so every decision
carries the same weight and a forward result can be placed beside a backtest
one without adjusting for size.
"""


@dataclass(frozen=True, slots=True)
class PaperContext:
    """Which series a decision belongs to. Four fields that travel together."""

    venue: str
    asset: str
    interval: str
    rule: str


@dataclass(frozen=True, slots=True)
class OpenPosition:
    """A paper position that has not been closed."""

    position_id: uuid.UUID
    side: Decision
    opened_at: datetime
    entry_price: Decimal
    quantity: Decimal
    notional: Decimal
    fees: Decimal

    def unrealised(self, price: Decimal) -> Decimal:
        """Marked to `price`, after the fees already paid to open."""
        moved = (price - self.entry_price) * self.side.sign
        return moved * self.quantity - self.fees


@dataclass(frozen=True, slots=True)
class Tick:
    """One decision and the information it was made on.

    Grouped because these five travel together from the CLI to the log to the
    position, and a call site that passes them separately eventually passes
    `candle_close` where `decided_at` belongs — which would make a late timer
    look like a decision taken on information it did not have.
    """

    decision: Decision
    price: Decimal
    candle_close: datetime
    """Close of the candle the decision was made on."""
    decided_at: datetime
    """When the engine ran. Later than `candle_close` when a timer fires late."""
    reasons: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Applied:
    """What one tick did, so a caller can report it without re-querying."""

    decision: Decision
    recorded: bool
    """False when this candle had already been decided — not an error."""
    closed: uuid.UUID | None = None
    opened: uuid.UUID | None = None
    realised: Decimal | None = None


@dataclass(frozen=True, slots=True)
class PaperBook:
    """The paper positions and decision log for one rule on one series.

    Holds the connection, the series identity and the cost model together,
    because every operation below needs all three and threading them through
    each call is how one of them ends up inconsistent between two of them.
    """

    connection: Connection[Any]
    context: PaperContext
    costs: CostModel = field(default_factory=CostModel)
    notional: Decimal = DEFAULT_NOTIONAL

    # ---- reads -----------------------------------------------------------

    def already_decided(self, candle_close: datetime) -> bool:
        """Whether this candle has already been decided for this rule."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM paper_decisions WHERE venue = %s AND asset = %s "
                "AND interval = %s AND rule = %s AND candle_close = %s",
                (*self._identity, candle_close),
            )
            return cursor.fetchone() is not None

    def open_position(self) -> OpenPosition | None:
        """The one open position for this rule and asset, if any."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT position_id, side, opened_at, entry_price, quantity, notional, "
                "fees FROM paper_positions WHERE venue = %s AND asset = %s "
                "AND interval = %s AND rule = %s AND closed_at IS NULL",
                self._identity,
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return OpenPosition(
            position_id=row[0],
            side=Decision(row[1]),
            opened_at=row[2],
            entry_price=row[3],
            quantity=row[4],
            notional=row[5],
            fees=row[6],
        )

    # ---- the tick --------------------------------------------------------

    def apply(self, tick: Tick) -> Applied:
        """Record one decision and move the paper position to match it.

        Committed as one transaction. A run that died between closing a
        position and opening the next would otherwise leave the book flat
        while its log said it had reversed, and the two would disagree for as
        long as nobody looked.
        """
        if self.already_decided(tick.candle_close):
            # The timer fired twice, or somebody ran it by hand beside the
            # timer. Same candle, same information, same decision.
            return Applied(decision=tick.decision, recorded=False)

        held = self.open_position()
        closed: uuid.UUID | None = None
        opened: uuid.UUID | None = None
        realised: Decimal | None = None

        if held is not None and held.side is not tick.decision:
            realised = self._close(held, tick)
            closed = held.position_id
            held = None

        if held is None and tick.decision is not Decision.FLAT:
            opened = self._open(tick)

        self._record(tick)
        self.connection.commit()
        return Applied(
            decision=tick.decision,
            recorded=True,
            closed=closed,
            opened=opened,
            realised=realised,
        )

    # ---- writes ----------------------------------------------------------

    @property
    def _identity(self) -> tuple[str, str, str, str]:
        return (
            self.context.venue,
            self.context.asset,
            self.context.interval,
            self.context.rule,
        )

    def _one_way_cost(self, notional: Decimal) -> Decimal:
        """Fee plus the half-spread crossed: the backtester's own charge."""
        return notional * self.costs.one_way_bps / BPS

    def _open(self, tick: Tick) -> uuid.UUID:
        position_id = uuid.uuid4()
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO paper_positions (position_id, venue, asset, interval, "
                "rule, side, quantity, notional, opened_at, entry_price, fees) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    position_id,
                    *self._identity,
                    tick.decision.value,
                    self.notional / tick.price,
                    self.notional,
                    tick.candle_close,
                    tick.price,
                    self._one_way_cost(self.notional),
                ),
            )
        return position_id

    def _close(self, held: OpenPosition, tick: Tick) -> Decimal:
        """Close the position and return what it realised, after both fees."""
        exit_notional = tick.price * held.quantity
        total_fees = held.fees + self._one_way_cost(exit_notional)
        moved = (tick.price - held.entry_price) * held.side.sign
        with self.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE paper_positions SET closed_at = %s, exit_price = %s, "
                "fees = %s, updated_at = now() WHERE position_id = %s",
                (tick.candle_close, tick.price, total_fees, held.position_id),
            )
        return moved * held.quantity - total_fees

    def _record(self, tick: Tick) -> None:
        """Append the decision, including the ones that changed nothing.

        A log of trades alone answers "what did it do" and not "what did it
        think", and the second question is what catches a rule that has
        quietly stopped producing signals at all.
        """
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO paper_decisions (decision_id, decided_at, candle_close, "
                "venue, asset, interval, rule, decision, price, reasons) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    uuid.uuid4(),
                    tick.decided_at,
                    tick.candle_close,
                    *self._identity,
                    tick.decision.value,
                    tick.price,
                    json.dumps(tick.reasons),
                ),
            )

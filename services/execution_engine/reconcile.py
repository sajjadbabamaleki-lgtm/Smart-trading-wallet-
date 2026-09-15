"""Comparing what we believe against what the venue says.

Invariant 8: the venue is authoritative, internal state reconciles against it
continuously, and an unexplained mismatch is a critical event (Phase 6 §45-46,
Phase 7 §9, Phase 8 §53). This module does the comparison and classifies what
it finds. It deliberately does not fix anything: adopting the venue's answer is
the Execution Engine's job, and stopping trading is the Risk Engine's, so a
reconciler that quietly repaired state would hide the very events these
invariants exist to surface.

The distinction that carries most of the weight is between *unresolved* and
*critical*:

* Unresolved — we cannot yet tell. An order we submitted a moment ago that the
  venue has not listed may simply not have arrived. The answer is no new risk
  until the next pass, not an alarm.
* Critical — the two views contradict each other in a way nothing benign
  explains. An order the venue has that we never sent, or a position we do not
  know about, means something else is trading this account, or that our record
  of reality is wrong. Either way trading stops.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from libs.exchange.models import OrderState, OrderStatus, Position
from libs.schemas.enums import Side
from services.execution_engine.orders import OrderRecord

# States in which the venue not listing an order is still ambiguous: we sent
# it, or we lost track of it, and either way the venue may simply not have
# processed it yet.
IN_FLIGHT = frozenset({OrderState.SUBMITTED, OrderState.UNKNOWN})


class Severity(StrEnum):
    INFO = "INFO"
    UNRESOLVED = "UNRESOLVED"
    CRITICAL = "CRITICAL"


class DiscrepancyKind(StrEnum):
    ORDER_UNKNOWN_TO_US = "ORDER_UNKNOWN_TO_US"
    ORDER_MISSING_AT_VENUE = "ORDER_MISSING_AT_VENUE"
    ORDER_STATE_DIFFERS = "ORDER_STATE_DIFFERS"
    FILL_QUANTITY_DIFFERS = "FILL_QUANTITY_DIFFERS"
    POSITION_UNKNOWN_TO_US = "POSITION_UNKNOWN_TO_US"
    POSITION_SIZE_DIFFERS = "POSITION_SIZE_DIFFERS"
    POSITION_MISSING_AT_VENUE = "POSITION_MISSING_AT_VENUE"


class Discrepancy(BaseModel):
    """One difference between the two views, and how bad it is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: DiscrepancyKind
    severity: Severity
    subject: str
    """The order id or asset the difference concerns."""
    believed: str
    observed: str


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    discrepancies: tuple[Discrepancy, ...] = ()

    @property
    def is_clean(self) -> bool:
        return not self.discrepancies

    @property
    def critical(self) -> tuple[Discrepancy, ...]:
        return tuple(d for d in self.discrepancies if d.severity is Severity.CRITICAL)

    @property
    def unresolved(self) -> tuple[Discrepancy, ...]:
        return tuple(d for d in self.discrepancies if d.severity is Severity.UNRESOLVED)

    @property
    def new_exposure_permitted(self) -> bool:
        """Invariant 7: neither a contradiction nor an unknown permits new risk."""
        return not self.critical and not self.unresolved


def believed_positions(
    records: dict[str, OrderRecord], sides: dict[str, Side]
) -> dict[str, Decimal]:
    """Net signed size per asset, from the fills this process knows about.

    This is a belief built from our own orders, which is exactly why it has to
    be reconciled: a position opened by an earlier process, by a human on the
    venue's own interface, or by a fill we never saw, is invisible here and
    shows up only in the comparison.
    """
    net: dict[str, Decimal] = defaultdict(Decimal)
    for record in records.values():
        if record.filled_quantity == 0:
            continue
        side = sides.get(record.client_order_id)
        if side is None:
            continue
        net[record.asset] += record.filled_quantity * side.sign
    return {asset: size for asset, size in net.items() if size != 0}


def reconcile_orders(
    records: dict[str, OrderRecord], venue: tuple[OrderStatus, ...]
) -> list[Discrepancy]:
    found: list[Discrepancy] = []
    by_id = {status.client_order_id: status for status in venue}

    for client_order_id, status in by_id.items():
        if client_order_id not in records:
            # Nothing benign explains this: we did not send it.
            found.append(
                Discrepancy(
                    kind=DiscrepancyKind.ORDER_UNKNOWN_TO_US,
                    severity=Severity.CRITICAL,
                    subject=client_order_id,
                    believed="no such order",
                    observed=str(status.state),
                )
            )

    for client_order_id, record in records.items():
        seen = by_id.get(client_order_id)
        if seen is None:
            if record.state.is_terminal:
                # A venue that forgets completed orders is normal.
                continue
            found.append(
                Discrepancy(
                    kind=DiscrepancyKind.ORDER_MISSING_AT_VENUE,
                    severity=(
                        Severity.UNRESOLVED if record.state in IN_FLIGHT else Severity.CRITICAL
                    ),
                    subject=client_order_id,
                    believed=str(record.state),
                    observed="absent",
                )
            )
            continue
        if seen.state is not record.state:
            found.append(
                Discrepancy(
                    kind=DiscrepancyKind.ORDER_STATE_DIFFERS,
                    # Not critical by itself: our view lags the venue's by
                    # design, and adopting the venue's answer resolves it.
                    severity=Severity.INFO,
                    subject=client_order_id,
                    believed=str(record.state),
                    observed=str(seen.state),
                )
            )
        if seen.filled_quantity != record.filled_quantity:
            found.append(
                Discrepancy(
                    kind=DiscrepancyKind.FILL_QUANTITY_DIFFERS,
                    severity=Severity.INFO,
                    subject=client_order_id,
                    believed=str(record.filled_quantity),
                    observed=str(seen.filled_quantity),
                )
            )
    return found


def reconcile_positions(
    believed: dict[str, Decimal], venue: tuple[Position, ...]
) -> list[Discrepancy]:
    found: list[Discrepancy] = []
    observed = {position.asset: position.size for position in venue if position.size != 0}

    for asset, size in observed.items():
        if asset not in believed:
            found.append(
                Discrepancy(
                    kind=DiscrepancyKind.POSITION_UNKNOWN_TO_US,
                    severity=Severity.CRITICAL,
                    subject=asset,
                    believed="flat",
                    observed=str(size),
                )
            )
        elif believed[asset] != size:
            found.append(
                Discrepancy(
                    kind=DiscrepancyKind.POSITION_SIZE_DIFFERS,
                    severity=Severity.CRITICAL,
                    subject=asset,
                    believed=str(believed[asset]),
                    observed=str(size),
                )
            )

    for asset, size in believed.items():
        if asset not in observed:
            # We think we are exposed and the venue says we are not. Either a
            # close we never saw, or a fill that never happened.
            found.append(
                Discrepancy(
                    kind=DiscrepancyKind.POSITION_MISSING_AT_VENUE,
                    severity=Severity.CRITICAL,
                    subject=asset,
                    believed=str(size),
                    observed="flat",
                )
            )
    return found


def reconcile(
    *,
    records: dict[str, OrderRecord],
    venue_orders: tuple[OrderStatus, ...],
    believed: dict[str, Decimal],
    venue_positions: tuple[Position, ...],
) -> ReconciliationReport:
    """Compare both views and report, without changing either."""
    return ReconciliationReport(
        discrepancies=tuple(
            reconcile_orders(records, venue_orders) + reconcile_positions(believed, venue_positions)
        )
    )

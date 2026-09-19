"""What the paper trader has done, and what it is holding.

The loop's output. It runs on the server, writes this into the repository and
pushes it, so the result can be read without anyone copying a terminal.

**What it reports and what it refuses to claim.** Realised profit and loss on
closed positions, marked-to-market on open ones, the decision log, and how long
since the last decision. It does not annualise, does not extrapolate, and does
not describe a positive number as an edge: the rules being traded here have
already failed a backtest, and a few weeks of forward results is a few weeks of
forward results.

The number that matters most in the early weeks is not the profit. It is
whether the loop ran at all — a gap in the decision log means the timer, the
download or the store stopped, and that is worth catching before a month of
missing decisions is mistaken for a month of flat ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from libs.config import load_settings
from libs.observability import configure_logging
from libs.storage import postgres as pg

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from psycopg import Connection

BPS: Final = Decimal(10000)


@dataclass(frozen=True, slots=True)
class Book:
    """One rule on one series, as the store holds it."""

    venue: str
    asset: str
    interval: str
    rule: str
    decisions: int
    first_decision: datetime
    last_decision: datetime
    closed: int
    wins: int
    realised: Decimal
    fees: Decimal
    open_side: str | None
    open_since: datetime | None
    open_entry: Decimal | None

    @property
    def win_rate(self) -> Decimal | None:
        """None with no closed positions. A rate over nothing is not zero."""
        if not self.closed:
            return None
        return Decimal(self.wins) / Decimal(self.closed) * 100


def _books(connection: Connection[Any]) -> list[Book]:
    """Every rule the paper trader has a record for.

    One query per concern rather than one clever join: the decision log and the
    position table have different grains, and a join across them would either
    multiply the decisions by the positions or need a subquery for each anyway.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT venue, asset, interval, rule, count(*), min(candle_close), "
            "max(candle_close) FROM paper_decisions "
            "GROUP BY venue, asset, interval, rule ORDER BY asset, rule"
        )
        logs = cursor.fetchall()

        cursor.execute(
            "SELECT venue, asset, interval, rule, count(*), "
            "count(*) FILTER (WHERE (exit_price - entry_price) * "
            "  (CASE side WHEN 'LONG' THEN 1 ELSE -1 END) * quantity - fees > 0), "
            "coalesce(sum((exit_price - entry_price) * "
            "  (CASE side WHEN 'LONG' THEN 1 ELSE -1 END) * quantity - fees), 0), "
            "coalesce(sum(fees), 0) "
            "FROM paper_positions WHERE closed_at IS NOT NULL "
            "GROUP BY venue, asset, interval, rule"
        )
        closed = {row[:4]: row[4:] for row in cursor.fetchall()}

        cursor.execute(
            "SELECT venue, asset, interval, rule, side, opened_at, entry_price "
            "FROM paper_positions WHERE closed_at IS NULL"
        )
        live = {row[:4]: row[4:] for row in cursor.fetchall()}

    books = []
    for venue, asset, interval, rule, count, first, last in logs:
        key = (venue, asset, interval, rule)
        settled = closed.get(key, (0, 0, Decimal(0), Decimal(0)))
        held = live.get(key, (None, None, None))
        books.append(
            Book(
                venue=venue,
                asset=asset,
                interval=interval,
                rule=rule,
                decisions=count,
                first_decision=first,
                last_decision=last,
                closed=settled[0],
                wins=settled[1],
                realised=settled[2],
                fees=settled[3],
                open_side=held[0],
                open_since=held[1],
                open_entry=held[2],
            )
        )
    return books


def _recent(connection: Connection[Any], *, limit: int) -> list[tuple[Any, ...]]:
    """The last few decisions, so a reader can see the loop is alive."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT candle_close, asset, rule, decision, price FROM paper_decisions "
            "ORDER BY candle_close DESC, asset LIMIT %s",
            (limit,),
        )
        return list(cursor.fetchall())


def render(books: list[Book], recent: list[tuple[Any, ...]], *, now: datetime) -> None:
    if not books:
        print("The paper trader has made no decisions yet.")
        print("Install the timer with `make paper-install`, or run one tick with")
        print("`make paper ASSET=BTC` to check it works.")
        return

    print(f"Paper trading, as of {now:%Y-%m-%d %H:%M} UTC")
    print()
    print(
        f"  {'asset':<5} {'rule':<20} {'decisions':>9} {'closed':>7} {'win%':>6} "
        f"{'realised':>10} {'holding':<22} last decision"
    )
    for book in books:
        win = "     -" if book.win_rate is None else f"{book.win_rate:5.1f}%"
        holding = "flat"
        if book.open_side and book.open_since:
            holding = f"{book.open_side} since {book.open_since:%m-%d %H:%M}"
        behind = (now - book.last_decision).total_seconds() / 3600
        print(
            f"  {book.asset:<5} {book.rule:<20} {book.decisions:>9} {book.closed:>7} "
            f"{win} {book.realised:>10.2f} {holding:<22} {behind:.1f}h ago"
        )

    print()
    print("  last decisions:")
    for moment, asset, rule, decision, price in recent:
        print(f"    {moment:%Y-%m-%d %H:%M}  {asset:<5} {rule:<20} {decision:<5} @ {price}")

    stale = [book for book in books if (now - book.last_decision).days >= 1]
    print()
    if stale:
        # The number that matters in the early weeks. A gap in the log means
        # the timer, the download or the store stopped, and a month of missing
        # decisions reads exactly like a month of flat ones.
        print("  ** the loop has not decided for over a day on:")
        for book in stale:
            print(f"       {book.asset} {book.rule} — last {book.last_decision:%Y-%m-%d %H:%M}")
        print("     Check `make paper-status`.")
    else:
        print("  the loop is current on every book.")

    print()
    print("  These rules have already failed a backtest. This is a forward record")
    print("  of what they do next, which is the one test that cannot be fitted —")
    print("  not a claim that any of them works.")


def main() -> int:
    import argparse  # noqa: PLC0415 - CLI-local

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recent", type=int, default=12)
    args = parser.parse_args()

    configure_logging()
    settings = load_settings()
    now = datetime.now(tz=UTC)
    with pg.connect(settings.postgres_dsn) as connection:
        render(_books(connection), _recent(connection, limit=args.recent), now=now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

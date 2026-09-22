"""Manual long/short trading with the stop loss always attached.

    python -m services.trader.cli status
    python -m services.trader.cli open  --symbol SOL --side long  --sl 140 --tp 170
    python -m services.trader.cli open  --symbol SOL --side short --sl 165 --rr 2 --execute
    python -m services.trader.cli tpsl  --symbol SOL --sl 150 --execute
    python -m services.trader.cli close --symbol SOL --execute

Without `--execute`, nothing is sent: `open` prints the exact order it would
place, with position size, leverage, loss at the stop and profit at the target.

The exchange (Hyperliquid by default, or Pacifica) and the keys come from
`TRADER_*` variables in `.env.trader`; see `services/trader/README.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs.exchange.errors import OrderOutcomeUnknownError, VenueError  # noqa: E402
from services.trader.config import (  # noqa: E402
    TraderConfigError,
    TraderSettings,
    load_trader_settings,
)
from services.trader.planner import PlanRejectedError, RiskLimits, TradePlan  # noqa: E402
from services.trader.trader import (  # noqa: E402
    TradeRefusedError,
    close_position,
    open_position,
    update_tpsl,
)
from services.trader.venue import Direction, Venue  # noqa: E402
from services.trader.venues.factory import build_venue  # noqa: E402

VenueFactory = Callable[[TraderSettings, bool], tuple[Venue, bool]]


def _decimal(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from exc
    if not value.is_finite() or value <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive number: {text!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trader", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", help="account, positions and TP/SL orders")

    open_cmd = commands.add_parser("open", help="open a long or short with SL and TP")
    open_cmd.add_argument("--symbol", default="SOL", type=str.upper)
    open_cmd.add_argument("--side", required=True, choices=[d.value for d in Direction])
    open_cmd.add_argument("--sl", required=True, type=_decimal, help="stop loss price")
    target = open_cmd.add_mutually_exclusive_group()
    target.add_argument("--tp", type=_decimal, help="take profit price")
    target.add_argument(
        "--rr", type=_decimal, help="take profit as a multiple of the stop distance, e.g. 2"
    )
    open_cmd.add_argument(
        "--risk", type=_decimal, help="percent of equity lost if the stop is hit (default 1)"
    )

    tpsl_cmd = commands.add_parser("tpsl", help="move the SL and/or TP of an open position")
    tpsl_cmd.add_argument("--symbol", default="SOL", type=str.upper)
    tpsl_cmd.add_argument("--sl", type=_decimal)
    tpsl_cmd.add_argument("--tp", type=_decimal)

    close_cmd = commands.add_parser("close", help="close an open position at market")
    close_cmd.add_argument("--symbol", default="SOL", type=str.upper)

    for command in (open_cmd, tpsl_cmd, close_cmd):
        command.add_argument(
            "--execute", action="store_true", help="actually send it (default: only show)"
        )
        command.add_argument(
            "--yes", action="store_true", help="skip the mainnet confirmation prompt"
        )
    return parser


def _default_factory(settings: TraderSettings, needs_signer: bool) -> tuple[Venue, bool]:
    return build_venue(settings, needs_signer=needs_signer)


def _confirm_mainnet(venue: Venue, args: argparse.Namespace) -> None:
    if not venue.is_mainnet or args.yes:
        return
    answer = input(f"{venue.name} MAINNET: this uses real money. Type 'yes' to send: ")
    if answer.strip().lower() != "yes":
        raise TradeRefusedError("not confirmed")


def _print_plan(plan: TradePlan) -> None:
    rows = [
        ("market", f"{plan.symbol} {plan.direction.value.upper()}"),
        ("entry (now)", f"{plan.entry_price}"),
        ("stop loss", f"{plan.stop_loss}"),
        ("take profit", f"{plan.take_profit}" if plan.take_profit is not None else "none"),
        ("size", f"{plan.amount} {plan.symbol}  (${plan.notional:.2f})"),
        ("leverage", f"{plan.leverage}x" + ("  (capped)" if plan.capped_by_leverage else "")),
        ("risk budget", f"${plan.risk_usd:.2f}"),
        ("loss at stop", f"-${plan.loss_at_stop:.2f}  (fees and slippage included)"),
    ]
    if plan.profit_at_target is not None:
        rows.append(("profit at target", f"+${plan.profit_at_target:.2f}  (after fees)"))
    if plan.reward_to_risk is not None:
        rows.append(("reward : risk", f"{plan.reward_to_risk:.2f} : 1"))
    for label, value in rows:
        print(f"  {label:<17} {value}")


def _network(venue: Venue) -> str:
    return f"{venue.name} {'MAINNET' if venue.is_mainnet else 'TESTNET'}"


async def _status(venue: Venue) -> None:
    account = await venue.account()
    print(f"exchange  {_network(venue)}")
    print(f"account   {venue.account_address}")
    print(f"equity    ${account.equity:.2f}   available ${account.available:.2f}")
    positions = await venue.positions()
    if not positions:
        print("positions none")
    for position in positions:
        price = await venue.price(position.symbol)
        label = "LONG" if position.is_long else "SHORT"
        sign = 1 if position.is_long else -1
        pnl = (price - position.entry_price) * position.amount * sign
        print(
            f"position  {position.symbol} {label} {position.amount} @ "
            f"{position.entry_price}  now {price}  uPnL ${pnl:.2f}"
        )
        for trigger in await venue.triggers(position.symbol):
            print(f"  trigger {trigger.trigger_price}")


async def _open(venue: Venue, args: argparse.Namespace, settings: TraderSettings) -> None:
    direction = Direction(args.side)
    take_profit = args.tp
    if args.rr is not None:
        price = await venue.price(args.symbol)
        distance = abs(price - args.sl)
        take_profit = (
            price + distance * args.rr
            if direction is Direction.LONG
            else price - distance * args.rr
        )
    limits = RiskLimits(
        risk_percent=args.risk or settings.default_risk_percent,
        max_leverage=settings.max_leverage,
        taker_fee_rate=settings.taker_fee_rate,
        slippage_percent=settings.slippage_percent,
    )
    result = await open_position(
        venue,
        symbol=args.symbol,
        direction=direction,
        stop_loss=args.sl,
        take_profit=take_profit,
        limits=limits,
        execute=args.execute,
    )
    _print_plan(result.plan)
    if result.executed and result.position is not None:
        print(f"  filled @ {result.position.entry_price}, size {result.position.amount}")
        if not result.stop_confirmed:
            print(
                "  WARNING: the stop loss could not be confirmed on the exchange. "
                "Check the position now."
            )


async def _run(args: argparse.Namespace, settings: TraderSettings, factory: VenueFactory) -> int:
    needs_signer = args.command != "status" and args.execute
    venue, uses_api_key = factory(settings, needs_signer)
    try:
        if not uses_api_key:
            print(
                "WARNING: TRADER_API_PRIVATE_KEY is the main wallet's own key. Use an API "
                "wallet instead, so the main key never leaves Phantom.",
                file=sys.stderr,
            )
        if args.command == "status":
            await _status(venue)
            return 0

        if args.execute:
            _confirm_mainnet(venue, args)
        print(f"[{_network(venue)}] {'SENT' if args.execute else 'DRY RUN — add --execute'}")

        if args.command == "open":
            await _open(venue, args, settings)
        elif args.command == "tpsl":
            if args.sl is None and args.tp is None:
                raise TradeRefusedError("give --sl and/or --tp")
            position = await update_tpsl(
                venue,
                symbol=args.symbol,
                stop_loss=args.sl,
                take_profit=args.tp,
                execute=args.execute,
            )
            print(
                f"  {position.symbol}: stop loss {args.sl or 'unchanged'}, "
                f"take profit {args.tp or 'unchanged'}"
            )
        else:
            position = await close_position(
                venue,
                symbol=args.symbol,
                slippage_percent=settings.slippage_percent,
                execute=args.execute,
            )
            label = "LONG" if position.is_long else "SHORT"
            print(f"  close {position.symbol} {label} {position.amount} at market")
        return 0
    finally:
        await venue.aclose()


def main(argv: list[str] | None = None, factory: VenueFactory = _default_factory) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_trader_settings()
        return asyncio.run(_run(args, settings, factory))
    except OrderOutcomeUnknownError as exc:
        print(f"UNKNOWN: {exc}", file=sys.stderr)
        return 3
    except TraderConfigError as exc:
        print(f"configuration: {exc}", file=sys.stderr)
        return 2
    except (PlanRejectedError, TradeRefusedError, VenueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

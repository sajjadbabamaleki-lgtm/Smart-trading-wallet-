#!/usr/bin/env python3
"""Place one test order on Hyperliquid testnet, through the whole chain (M8).

    python -m services.execution_engine.cli --side BUY --notional 20 --check
    python -m services.execution_engine.cli --side BUY --notional 20
    python -m services.execution_engine.cli --account
    python -m services.execution_engine.cli --cancel <client-order-id>

This exists so that the path from a proposal to a venue order can be run end to
end by a person, and so that the first time it runs is not the first time a
strategy depends on it.

It does not shortcut the chain. A proposal goes to the Risk Engine, the Risk
Engine issues an intent or refuses, the Execution Engine re-validates that
intent and builds the one order it authorises, and only then does the adapter
see anything (Build 0.1 Rev.1 §48). Nothing here calls `place_order` directly,
because nothing in application code is allowed to.

`--check` stops after the Risk Engine has answered, so the decision and the
order that would be submitted can be read before anything is sent. It is the
default way to use this for the first time.

Every refusal this can hit is a refusal by design: the kill switch is off, the
environment is not TESTNET, no credential is configured, the asset is not on
the allowlist, the market data is stale. The output names which one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402

from libs.config import ConfigurationError, load_settings  # noqa: E402
from libs.domain.clock import SystemClock  # noqa: E402
from libs.exchange.hyperliquid.adapter import (  # noqa: E402
    HyperliquidAdapter,
    UnsupportedEnvironmentError,
)
from libs.observability.logging import configure_logging, get_logger  # noqa: E402
from libs.schemas.enums import Side  # noqa: E402
from services.execution_engine.engine import ExecutionEngine, IntentRefusedError  # noqa: E402
from services.risk_engine.engine import MarketSnapshot, RiskEngine  # noqa: E402
from services.risk_engine.models import RiskOutcome, TradeProposal  # noqa: E402

logger = get_logger("execution.cli")

# Far enough that a test order is not stopped out by the spread, close enough
# that it is a real stop. Invariant 6 requires one to exist at all: a position
# with no stated downside cannot be proposed.
DEFAULT_STOP_FRACTION = Decimal("0.02")


async def _account(adapter: HyperliquidAdapter) -> dict[str, Any]:
    state = await adapter.get_account_state()
    orders = await adapter.get_orders()
    return {
        "address": adapter.address,
        "equity": str(state.equity),
        "available_margin": str(state.available_margin),
        "positions": [
            {"asset": p.asset, "size": str(p.size), "entry": str(p.entry_price)}
            for p in state.positions
        ],
        "open_orders": [
            {"client_order_id": o.client_order_id, "venue_order_id": o.venue_order_id}
            for o in orders
        ],
    }


async def _run(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"configuration refused: {exc}", file=sys.stderr)
        return 2

    configure_logging(settings.log_level, stream=sys.stderr)
    clock = SystemClock()

    try:
        adapter = HyperliquidAdapter(settings, clock=clock)
    except UnsupportedEnvironmentError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    try:
        if args.account:
            print(json.dumps(await _account(adapter), indent=2))
            return 0

        if args.cancel:
            status = await adapter.cancel_order(args.cancel)
            print(json.dumps(status.model_dump(mode="json"), indent=2))
            return 0

        return await _order(args, adapter, settings, clock)
    except (httpx.TransportError, httpx.HTTPStatusError) as exc:
        # Only reads reach here. `place_order` handles its own ambiguity and
        # returns UNKNOWN rather than raising, so a submission can never be
        # turned into a clean-looking failure by this handler.
        print(
            f"could not reach the venue at {settings.venue_endpoint}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2
    finally:
        await adapter.aclose()


async def _order(
    args: argparse.Namespace, adapter: HyperliquidAdapter, settings: Any, clock: SystemClock
) -> int:
    market = await adapter.get_market_state(args.asset)
    if market.bid_price is None or market.ask_price is None:
        print(
            f"{args.asset} is not quoted on both sides; refusing to price an order", file=sys.stderr
        )
        return 1

    side = Side[args.side.upper()]
    reference = market.ask_price if side is Side.BUY else market.bid_price
    stop_fraction = Decimal(str(args.stop_fraction))
    stop = reference * (
        (Decimal(1) - stop_fraction) if side is Side.BUY else (Decimal(1) + stop_fraction)
    )

    risk = RiskEngine(settings, clock=clock)
    execution = ExecutionEngine(settings, risk.ledger, clock=clock)

    proposal = TradeProposal(
        correlation_id=args.correlation_id,
        asset=args.asset.upper(),
        side=side,
        notional_usd=Decimal(str(args.notional)),
        stop_price=stop,
        proposed_at=clock.now(),
    )
    # The bid is what the Risk Engine measures staleness and sizing against.
    decision = risk.evaluate(
        proposal, market=MarketSnapshot(bid=market.bid_price, observed_at=market.observed_at)
    )

    report: dict[str, Any] = {
        "settings": settings.describe(),
        "market": {
            "bid": str(market.bid_price),
            "ask": str(market.ask_price),
            "observed_at": market.observed_at.isoformat(),
        },
        "proposal": {
            "side": side.value,
            "notional_usd": str(proposal.notional_usd),
            "stop_price": str(stop),
        },
        "decision": decision.model_dump(mode="json"),
    }

    if decision.outcome is RiskOutcome.REJECTED or decision.intent_id is None:
        print(json.dumps(report, indent=2))
        print(
            "the Risk Engine refused this proposal: "
            + ", ".join(reason.value for reason in decision.reasons),
            file=sys.stderr,
        )
        return 1

    intent = risk.ledger.issued(decision.intent_id)
    try:
        request = execution.prepare(intent, price=reference)
    except IntentRefusedError as exc:
        report["revalidation"] = [reason.value for reason in exc.reasons]
        print(json.dumps(report, indent=2))
        print(f"re-validation refused the intent: {exc}", file=sys.stderr)
        return 1

    report["order"] = request.model_dump(mode="json")

    if args.check:
        report["submitted"] = False
        print(json.dumps(report, indent=2, default=str))
        print("--check: nothing was sent to the venue.", file=sys.stderr)
        return 0

    execution.mark_submitted(request.client_order_id)
    status = await adapter.place_order(request)
    record = execution.apply(status)

    report["submitted"] = True
    report["status"] = status.model_dump(mode="json")
    report["record_state"] = record.state.value
    print(json.dumps(report, indent=2, default=str))

    # An unknown outcome is not a failure, and must not be reported as success
    # either: Invariant 7 forbids new exposure until the venue has been asked.
    if execution.unresolved:
        print(
            f"outcome unknown for {request.client_order_id}. Ask the venue with --account "
            "before proposing anything else.",
            file=sys.stderr,
        )
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="BTC")
    parser.add_argument("--side", default="BUY", choices=["BUY", "SELL", "buy", "sell"])
    parser.add_argument("--notional", default="20", help="order size in USD")
    parser.add_argument(
        "--stop-fraction",
        dest="stop_fraction",
        default=str(DEFAULT_STOP_FRACTION),
        help="stop distance as a fraction of price (0.02 = 2%%)",
    )
    parser.add_argument("--correlation-id", dest="correlation_id", default="manual-testnet-order")
    parser.add_argument(
        "--check",
        action="store_true",
        help="decide and build the order, then stop without sending it",
    )
    parser.add_argument("--account", action="store_true", help="show account, positions and orders")
    parser.add_argument("--cancel", help="cancel by client order id")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())

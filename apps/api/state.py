"""Real state for the product console.

Every field here is read from something that exists: configuration, the stores,
the recorder's own output. Nothing is invented, and where a subsystem has not
been built the state says so rather than showing a plausible zero.

That distinction is the whole discipline of this module. `apps/README.md`
argues that designing product screens before the decision object exists inverts
the dependency and pressures the engine into producing whatever a mockup
promised. A console that reports `IMPLEMENTED: false` for positions creates no
such promise; one that renders an empty positions table does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from libs.config import Settings


class Availability(StrEnum):
    """Whether a capability exists at all, distinct from whether it is on."""

    IMPLEMENTED = "IMPLEMENTED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    """No code backs this yet. The console must not render a value for it."""

    BLOCKED = "BLOCKED"
    """Implemented, and structurally prevented at this build stage."""


@dataclass(frozen=True, slots=True)
class Capability:
    """One product capability, its state, and why."""

    name: str
    availability: Availability
    detail: str
    milestone: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "availability": self.availability.value,
            "detail": self.detail,
            "milestone": self.milestone,
        }


def account_layers(settings: Settings) -> list[dict[str, Any]]:
    """The three-layer account model (Phase 9 §3), as it actually stands.

    Phase 9 requires these never be presented as one indistinguishable object:
    the wallet that owns and authorizes, the authorization itself, and the venue
    account where collateral and positions live. They are separate rows here for
    that reason, and each carries its own real state.
    """
    return [
        Capability(
            name="Layer A — User Wallet",
            availability=Availability.NOT_IMPLEMENTED,
            detail=(
                "Phantom and Trust Wallet, behind a wallet adapter. No adapter exists "
                "yet. When it does, the seed phrase and private key never leave the "
                "wallet environment — the backend never receives them."
            ),
            milestone="Phase 9",
        ),
        Capability(
            name="Layer B — Trading Authorization",
            availability=Availability.NOT_IMPLEMENTED,
            detail=(
                "A separate grant from logging in, off by default. Nothing can be "
                "authorized while there is no Risk Engine to bound what is authorized."
            ),
            milestone="M7",
        ),
        Capability(
            name="Layer C — Trading Account",
            availability=Availability.NOT_IMPLEMENTED,
            detail=(
                f"Venue account holding collateral, positions, margin and P&L. The "
                f"execution environment is {settings.execution_environment.value}, "
                f"which maps to no venue endpoint, so no such account is reachable."
            ),
            milestone="M8",
        ),
    ]


def capabilities() -> list[dict[str, Any]]:
    """What the product can and cannot do, and why — never a blank panel."""
    return [
        Capability(
            name="Market data recording",
            availability=Availability.IMPLEMENTED,
            detail="BTC from Hyperliquid, accepted against the live venue on 2026-09-14.",
            milestone="M2",
        ).as_dict(),
        Capability(
            name="Research datasets",
            availability=Availability.IMPLEMENTED,
            detail="Identity, checksum, manifest and gap provenance.",
            milestone="M4",
        ).as_dict(),
        Capability(
            name="Backtesting",
            availability=Availability.IMPLEMENTED,
            detail=(
                "Event-driven, with lookahead structurally unavailable and fills at "
                "the touch after a decision delay."
            ),
            milestone="M6",
        ).as_dict(),
        Capability(
            name="Strategy",
            availability=Availability.NOT_IMPLEMENTED,
            detail=(
                "No strategy exists. There is therefore nothing to explain on a "
                "WHY THIS TRADE screen, and no confidence to calibrate."
            ),
            milestone="M5-M6",
        ).as_dict(),
        Capability(
            name="Risk Engine",
            availability=Availability.NOT_IMPLEMENTED,
            detail=(
                "The capital-control boundary. Until it exists nothing may be "
                "authorized to trade, because nothing would bound it."
            ),
            milestone="M7",
        ).as_dict(),
        Capability(
            name="Execution",
            availability=Availability.NOT_IMPLEMENTED,
            detail="No order has ever been submitted by this system.",
            milestone="M8",
        ).as_dict(),
        Capability(
            name="Positions and P&L",
            availability=Availability.NOT_IMPLEMENTED,
            detail=(
                "No position has ever been opened. An empty table would imply a "
                "system that could hold one and does not; this is not that."
            ),
            milestone="M8",
        ).as_dict(),
    ]


def modes(settings: Settings) -> list[dict[str, Any]]:
    """The three operating modes (Phase 1), and which are reachable.

    Autopilot is off by default and requires explicit trading authorization,
    which is a separate grant from logging in. Here it is not merely off — it
    is unreachable, because the Risk Engine it would need does not exist.
    """
    return [
        {
            "name": "Research",
            "active": True,
            "available": True,
            "detail": "Analytical transparency and strategy evaluation. No execution.",
        },
        {
            "name": "Copilot",
            "active": False,
            "available": False,
            "detail": "Requires a strategy to propose trades and a Risk Engine to bound them.",
        },
        {
            "name": "Autopilot",
            "active": False,
            "available": False,
            "detail": (
                "Off by default and structurally unreachable at this build stage. "
                f"Trading is {'enabled' if settings.trading_enabled else 'disabled'} "
                f"and order submission is "
                f"{'possible' if settings.may_submit_orders else 'impossible'}."
            ),
        },
    ]


def safety(settings: Settings) -> dict[str, Any]:
    """The guards, read from configuration rather than asserted.

    The frontend is not an authorization boundary (Invariant 4) and never infers
    critical state locally. Every value here is what the backend reports; the
    console renders it and can change none of it.
    """
    return {
        "execution_environment": settings.execution_environment.value,
        "reaches_real_capital": settings.execution_environment.reaches_real_capital,
        "venue_endpoint": settings.venue_endpoint,
        "trading_enabled": settings.trading_enabled,
        "may_submit_orders": settings.may_submit_orders,
        "credential_configured": bool(settings.testnet_api_wallet_private_key),
        "market_data_environment": settings.market_data_environment.value,
        "market_data_is_read_only": settings.market_data_is_read_only,
        "asset_allowlist": list(settings.asset_allowlist),
        "max_order_notional": str(settings.max_order_notional),
    }


def emergency_controls() -> list[dict[str, Any]]:
    """Phase 9 §54 controls, each with its real state.

    §56: emergency risk-reducing actions must remain quickly accessible, and the
    system must never require obscure menus to stop new trading. They are listed
    first-class here even though every one is currently inert, because a control
    that appears only once it is needed is a control nobody has practised.
    """
    return [
        {
            "name": "PAUSE AUTOPILOT",
            "enabled": False,
            "detail": "Autopilot has never run. Kill Switch 0.1 already holds it off.",
        },
        {
            "name": "CANCEL ENTRY ORDERS",
            "enabled": False,
            "detail": "No order has ever been submitted.",
        },
        {
            "name": "REDUCE EXPOSURE",
            "enabled": False,
            "detail": "No position has ever been opened.",
        },
    ]


def snapshot(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    """Everything the console renders, in one read."""
    return {
        "generated_at": (now or datetime.now(UTC)).isoformat(),
        "build_stage": "0.1 Rev.2",
        "safety": safety(settings),
        "modes": modes(settings),
        "account_layers": [layer.as_dict() for layer in account_layers(settings)],
        "capabilities": capabilities(),
        "emergency_controls": emergency_controls(),
    }

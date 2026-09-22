"""Build the configured venue from settings."""

from __future__ import annotations

from libs.exchange.errors import VenueError
from libs.exchange.pacifica.client import PacificaClient, PacificaNetwork
from libs.exchange.pacifica.signing import Signer, SigningError, check_account, load_keypair
from services.trader.config import TraderConfigError, TraderSettings, VenueName
from services.trader.venue import Venue
from services.trader.venues.hyperliquid import HyperliquidVenue
from services.trader.venues.pacifica import PacificaVenue


def build_venue(settings: TraderSettings, *, needs_signer: bool) -> tuple[Venue, bool]:
    """The venue, and whether it signs with a separate API key (the safe setup)."""
    if not settings.account:
        raise TraderConfigError("TRADER_ACCOUNT is not set (your main wallet's public address)")
    secret = settings.api_private_key.get_secret_value()
    if needs_signer and not secret:
        raise TraderConfigError("TRADER_API_PRIVATE_KEY is not set; it is needed to send orders")

    if settings.venue is VenueName.HYPERLIQUID:
        try:
            venue = HyperliquidVenue.connect(
                mainnet=settings.is_mainnet,
                account_address=settings.account,
                api_wallet_key=secret or None,
            )
        except VenueError as exc:
            raise TraderConfigError(str(exc)) from exc
        return venue, venue.signs_as_api_wallet

    try:
        account = check_account(settings.account)
        signer = Signer(account=account, keypair=load_keypair(secret)) if secret else None
    except SigningError as exc:
        raise TraderConfigError(str(exc)) from exc
    network = PacificaNetwork.MAINNET if settings.is_mainnet else PacificaNetwork.TESTNET
    client = PacificaClient(network, account=account, signer=signer)
    return PacificaVenue(client), signer is None or signer.is_agent

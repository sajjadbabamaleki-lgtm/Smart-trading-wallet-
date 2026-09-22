"""Pacifica venue integration — perpetual futures on Solana.

Separate from the Hyperliquid research pipeline. The API shapes come from
Pacifica's API reference and official Python SDK (`pacifica-fi/python-sdk`);
like the Hyperliquid layer, they have not yet been verified against a live
connection from this repository.
"""

from libs.exchange.pacifica.client import (
    AccountSnapshot,
    MarketSpec,
    OrderOutcomeUnknownError,
    OrderSnapshot,
    PacificaClient,
    PacificaError,
    PacificaNetwork,
    PositionSnapshot,
    PriceSnapshot,
    StopLeg,
)
from libs.exchange.pacifica.signing import Signer, SigningError, canonical_message, load_keypair

__all__ = [
    "AccountSnapshot",
    "MarketSpec",
    "OrderOutcomeUnknownError",
    "OrderSnapshot",
    "PacificaClient",
    "PacificaError",
    "PacificaNetwork",
    "PositionSnapshot",
    "PriceSnapshot",
    "Signer",
    "SigningError",
    "StopLeg",
    "canonical_message",
    "load_keypair",
]

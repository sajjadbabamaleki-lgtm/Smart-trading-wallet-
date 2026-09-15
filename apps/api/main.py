"""The app's HTTP boundary.

Read-only. Invariant 4: the frontend is not an authorization boundary, so there
is no endpoint here that could enable trading, move funds, or authorize
anything. A compromised client cannot reach capital by asking.

Trading and swap actions arrive as deliberate, separately authorized endpoints
when the Risk Engine exists to bound them (M7), not by relaxing this.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.api.data import app_state
from libs.config import load_settings

CONSOLE = Path(__file__).resolve().parents[1] / "console"

app = FastAPI(title="Smart Trading Wallet", version="0.1")


@app.get("/api/app")
def read_app_state() -> dict[str, Any]:
    """Wallet, network and market state for the four screens."""
    return app_state(load_settings())


@app.get("/api/health")
def read_health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(CONSOLE / "index.html")


app.mount("/static", StaticFiles(directory=CONSOLE), name="static")

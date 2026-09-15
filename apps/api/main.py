"""The product console's HTTP boundary.

Read-only, and that is structural rather than a phase we will grow out of
casually. Invariant 4: the frontend is not an authorization boundary and never
infers critical state locally. This API therefore exposes no mutation at all —
there is no endpoint that could enable trading, widen a limit, or authorize
anything, so a compromised console cannot reach capital by asking nicely.

When the Risk Engine exists (M7) and controls become real, each one arrives as
a deliberate endpoint with its own authorization, not by relaxing this.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.api.state import snapshot
from libs.config import load_settings

CONSOLE = Path(__file__).resolve().parents[1] / "console"

app = FastAPI(
    title="Smart Trading Wallet — Console",
    description="Read-only view of real system state.",
    version="0.1",
)


@app.get("/api/state")
def read_state() -> dict[str, Any]:
    """Everything the console renders.

    Settings are loaded per request rather than cached at import: a console
    that keeps reporting `trading_enabled: false` after the configuration
    changed would be showing a stale safety claim, which is the one kind of
    staleness that matters here.
    """
    return snapshot(load_settings())


@app.get("/api/health")
def read_health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(CONSOLE / "index.html")


app.mount("/static", StaticFiles(directory=CONSOLE), name="static")

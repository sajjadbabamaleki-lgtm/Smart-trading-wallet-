"""Write dashboard/data.json from the paper ledgers.

The dashboard page fetches this file; the daily run republishes only it.

    python -m research.paper_trading.export_dashboard
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "dashboard" / "data.json"
GATE_DAYS = 60
GATE_SHARPE = 0.5
GATE_MAX_DD = -25.0
STOP_DD = -30.0


def _series(ledger: Path) -> pd.DataFrame:
    path = ledger / "equity.csv"
    if not path.exists():
        return pd.DataFrame(columns=["day", "equity", "return_pct"])
    return pd.read_csv(path)


def _stats(eq: pd.DataFrame, start_equity: float) -> dict[str, float | int | None]:
    if eq.empty:
        return {"days": 0, "total_pct": 0.0, "max_dd_pct": 0.0, "sharpe": None}
    e = eq["equity"].astype(float)
    r = eq["return_pct"].astype(float) / 100
    sharpe = None
    if len(r) > 1 and r.std() > 0:
        sharpe = round(float(r.mean() / r.std() * math.sqrt(365)), 2)
    return {
        "days": len(eq),
        "total_pct": round((float(e.iloc[-1]) / start_equity - 1) * 100, 2),
        "max_dd_pct": round(float((e / e.cummax() - 1).min() * 100), 2),
        "sharpe": sharpe,
    }


def build() -> dict[str, object]:
    ledger = HERE / "ledger"
    state = json.loads((ledger / "state.json").read_text())
    live = _series(ledger)
    start_equity = 10_000.0
    stats = _stats(live, start_equity)
    dd = stats["max_dd_pct"] or 0.0
    sharpe = stats["sharpe"]
    if dd <= STOP_DD:
        gate = "stop"
    elif int(stats["days"] or 0) < GATE_DAYS:
        gate = "collecting"
    elif sharpe is not None and sharpe > GATE_SHARPE and dd > GATE_MAX_DD:
        gate = "pass"
    else:
        gate = "fail"
    positions = sorted(state["positions"].items(), key=lambda kv: -abs(kv[1]))
    backfill = _series(HERE / "ledger_backfill")
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "as_of": state["last_day"][:10],
        "leverage": state.get("leverage", 1.5),
        "start_equity": start_equity,
        "equity": round(float(state["equity"]), 2),
        "stats": stats,
        "gate": {
            "status": gate,
            "days_needed": GATE_DAYS,
            "sharpe_min": GATE_SHARPE,
            "max_dd_limit": GATE_MAX_DD,
            "stop_dd": STOP_DD,
        },
        "live": live[["day", "equity", "return_pct"]].to_dict(orient="records"),
        "positions": [{"coin": c, "weight": w} for c, w in positions],
        "backfill": {
            "stats": _stats(backfill, start_equity),
            "equity": backfill[["day", "equity"]].to_dict(orient="records"),
        },
        "backtest": {"cagr_1_5x_2022_26": 32.2, "max_dd_1_5x": -36.5},
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

"""Daily paper trader for the EXP-007 candidate portfolio on Hyperliquid.

Paper only: it reads public market data and writes a ledger. It holds no key
and cannot place an order.

Each run processes every completed UTC day since the last one in the ledger:
it marks yesterday's positions to today's close, charges funding and trading
costs, then sets new target weights from data up to today's close.

    python -m research.paper_trading.trader              # live ledger
    python -m research.paper_trading.trader --backfill-from 2026-01-01
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import pandas as pd

from research.paper_trading import hl_data
from research.paper_trading.strategies import (
    TA_COINS,
    combine,
    crash_weights,
    liquid_universe,
    ml_features,
    ml_weights,
    trend_weights,
)

HERE = Path(__file__).resolve().parent
MODEL_PATH = HERE / "model" / "ml_lgbm.txt"
START_EQUITY = 10_000.0
LEVERAGE = 1.5
COST_PER_SIDE = 0.001  # taker fee + slippage, per unit of notional traded
MAX_GROSS = 3.0
MAX_PER_COIN = 0.5
MIN_WEIGHT = 1e-4  # smaller targets are treated as flat
UNIVERSE_SIZE = 40  # coins fetched each run: the most liquid by 24h volume, plus held ones


def fetch(held: list[str]) -> dict[str, object]:
    ctx = hl_data._post({"type": "metaAndAssetCtxs"})
    assert isinstance(ctx, list)
    meta, stats = ctx
    live = [
        (float(s["dayNtlVlm"]), a["name"])
        for a, s in zip(meta["universe"], stats, strict=True)
        if not a.get("isDelisted", False)
    ]
    coins = [c for _, c in sorted(live, reverse=True)[:UNIVERSE_SIZE]]
    coins = list(dict.fromkeys(coins + TA_COINS + held))
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    d1 = {c: hl_data.candles(c, "1d") for c in coins}
    d1 = {c: b[b["close_ms"] < now_ms] for c, b in d1.items() if len(b)}  # completed days only
    h4 = {c: hl_data.candles(c, "4h") for c in TA_COINS}
    h4 = {c: b[b["close_ms"] < now_ms] for c, b in h4.items() if len(b)}
    start = now_ms - 90 * hl_data.DAY_MS  # features need 7 days of funding
    fund = {c: hl_data.daily_funding(c, start) for c in coins}
    return {"d1": d1, "h4": h4, "fund": fund}


def build(data: dict[str, object]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    d1 = data["d1"]
    assert isinstance(d1, dict)
    close = pd.DataFrame({c: b["close"] for c, b in d1.items()}).sort_index()
    # Candles before a coin's launch are back-filled with zero volume; drop them.
    vol = pd.DataFrame({c: b["v"] * b["close"] for c, b in d1.items()}).reindex(close.index)
    close = close.where(vol > 0)
    fund = data["fund"]
    assert isinstance(fund, dict)
    funding = pd.DataFrame(fund).reindex(close.index).fillna(0.0)
    return close, vol, funding


def target_weights(
    data: dict[str, object], close: pd.DataFrame, vol: pd.DataFrame, funding: pd.DataFrame
) -> pd.DataFrame:
    days = close.index
    h4 = data["h4"]
    d1 = data["d1"]
    assert isinstance(h4, dict)
    assert isinstance(d1, dict)
    trend = trend_weights(h4, {c: d1[c] for c in TA_COINS if c in d1}, days)
    crash = crash_weights(close, vol)
    universe = liquid_universe(close, vol, top_n=30)
    x = ml_features(close, vol, funding, universe)
    booster = lgb.Booster(model_file=str(MODEL_PATH))
    pred = pd.Series(booster.predict(x), index=x.index).unstack()
    ml = ml_weights(pred.reindex(days), close)
    w = combine({"crash": crash, "trend": trend, "ml": ml}, LEVERAGE)
    w = w.clip(-MAX_PER_COIN, MAX_PER_COIN)
    gross = w.abs().sum(axis=1)
    return w.div((gross / MAX_GROSS).clip(lower=1.0), axis=0)


def step_days(
    ledger: Path, close: pd.DataFrame, funding: pd.DataFrame, weights: pd.DataFrame, start: str
) -> list[dict[str, object]]:
    state_file = ledger / "state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text())
    else:
        state = {"equity": START_EQUITY, "last_day": None, "positions": {}, "leverage": LEVERAGE}
    ret = close.pct_change(fill_method=None).fillna(0.0)
    days = [d for d in close.index if d >= pd.Timestamp(start, tz="UTC")]
    if state["last_day"]:
        days = [d for d in days if d > pd.Timestamp(state["last_day"])]
    rows: list[dict[str, object]] = []
    trades: list[dict[str, object]] = []
    for day in days:
        pos = pd.Series(state["positions"], dtype=float)
        r = ret.loc[day].reindex(pos.index).fillna(0.0)
        f = funding.loc[day].reindex(pos.index).fillna(0.0)
        price_pnl = float((pos * r).sum())
        funding_pnl = -float((pos * f).sum())
        new = weights.loc[day]
        new = new[new.abs() > MIN_WEIGHT]
        all_coins = pos.index.union(new.index)
        delta = new.reindex(all_coins).fillna(0.0) - pos.reindex(all_coins).fillna(0.0)
        cost = float(delta.abs().sum()) * COST_PER_SIDE
        day_ret = price_pnl + funding_pnl - cost
        state["equity"] = float(state["equity"]) * (1 + day_ret)
        state["positions"] = {c: round(float(v), 6) for c, v in new.items()}
        state["last_day"] = day.isoformat()
        rows.append(
            {
                "day": f"{day:%Y-%m-%d}",
                "equity": round(state["equity"], 2),
                "return_pct": round(day_ret * 100, 3),
                "price_pct": round(price_pnl * 100, 3),
                "funding_pct": round(funding_pnl * 100, 3),
                "cost_pct": round(cost * 100, 3),
                "gross": round(float(new.abs().sum()), 3),
                "net": round(float(new.sum()), 3),
            }
        )
        trades.extend(
            {"day": f"{day:%Y-%m-%d}", "coin": c, "change": round(float(v), 4)}
            for c, v in delta.items()
            if abs(v) > MIN_WEIGHT
        )
    ledger.mkdir(parents=True, exist_ok=True)
    _append_csv(ledger / "equity.csv", rows)
    _append_csv(ledger / "trades.csv", trades)
    state_file.write_text(json.dumps(state, indent=1, sort_keys=True))
    return rows


def _append_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    df.to_csv(path, mode="a", header=not path.exists(), index=False)


def report(ledger: Path, rows: list[dict[str, object]]) -> str:
    state = json.loads((ledger / "state.json").read_text())
    eq = pd.read_csv(ledger / "equity.csv")
    total = (state["equity"] / START_EQUITY - 1) * 100
    peak = eq["equity"].cummax()
    dd = ((eq["equity"] / peak - 1).min()) * 100
    pos = sorted(state["positions"].items(), key=lambda kv: -abs(kv[1]))
    lines = [
        f"Paper portfolio as of {state['last_day'][:10]} (leverage {LEVERAGE}x)",
        f"Equity ${state['equity']:,.2f}  total {total:+.2f}%  max drawdown {dd:.2f}%",
        f"Days processed this run: {len(rows)}"
        + (f", last day {rows[-1]['return_pct']:+.2f}%" if rows else ""),
        "Largest positions (fraction of equity, + long / - short):",
        *[f"  {c:8s} {w:+.3f}" for c, w in pos[:12]],
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-from", help="simulate from this date into ledger_backfill/")
    args = ap.parse_args()
    ledger = HERE / ("ledger_backfill" if args.backfill_from else "ledger")
    held = []
    if (ledger / "state.json").exists():
        held = list(json.loads((ledger / "state.json").read_text())["positions"])
    data = fetch(held)
    close, vol, funding = build(data)
    weights = target_weights(data, close, vol, funding)
    last_complete = close.index[-1]
    start = args.backfill_from or f"{last_complete:%Y-%m-%d}"
    rows = step_days(ledger, close, funding, weights, start)
    print(report(ledger, rows))


if __name__ == "__main__":
    main()

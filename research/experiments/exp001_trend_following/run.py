"""EXP-001: volatility-targeted trend following on crypto perpetual futures.

Research only. Nothing here can place an order (research/README.md).

Hypothesis: time-series momentum (Moskowitz, Ooi & Pedersen 2012; Liu &
Tsyvinski 2021) survives realistic perpetual-futures costs on the liquid
majors, and survives out of sample.

Data is fetched from public GitHub mirrors of Binance daily klines and
Binance BTCUSDT funding history, pinned by commit so the run is
reproducible. The venue APIs are unreachable from the research sandbox.
Data is cached in research/datasets/exp001 (git-ignored).

    pip install pandas numpy
    python research/experiments/exp001_trend_following/run.py
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).resolve().parents[2] / "datasets" / "exp001"

MAJORS_SRC = (
    "https://raw.githubusercontent.com/marek3993/trendatlas-crypto/"
    "af0b7586667b6c28d6054a4153d1f0901dcb3222/data/ohlcv/{sym}_1d.csv"
)
MAJORS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX", "LINK", "LTC", "DOT", "AVAX"]
FUNDING_SRC = (
    "https://raw.githubusercontent.com/VivekWar/Crypto-Funding-Rate-Arbitrage/"
    "dcbe60250451a8f7d5d230500a9176032e78b7c7/notebooks/BTCUSDT_historical_funding.csv"
)

SPLIT = "2022-01-01"  # everything from here on is out of sample


def fetch(url: str, name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.exists():
        urllib.request.urlretrieve(url, path)  # noqa: S310 - fixed https URLs
    return path


def load_prices() -> pd.DataFrame:
    closes = {}
    for sym in MAJORS:
        f = fetch(MAJORS_SRC.format(sym=f"{sym}USDT"), f"{sym}USDT_1d.csv")
        closes[sym] = pd.read_csv(f, parse_dates=["date"]).set_index("date")["close"]
    return pd.DataFrame(closes).sort_index()


def load_funding() -> pd.Series:
    f = pd.read_csv(fetch(FUNDING_SRC, "BTCUSDT_funding.csv"))
    f.index = pd.to_datetime(f["fundingTime"])
    return f["fundingRate"].resample("1D").sum()  # three 8h payments per day


def backtest(
    px: pd.DataFrame,
    funding: pd.Series,
    lookbacks: tuple[int, ...] = (20, 60, 120),
    long_only: bool = True,
    target_vol: float = 0.60,
    max_gross: float = 2.0,
    cost: float = 0.0015,
    funding_mult: float = 2.0,
) -> tuple[pd.Series, pd.DataFrame]:
    """Daily returns of the strategy on 1 unit of margin capital.

    Signal: mean of sign(return over L days) across lookbacks, in [-1, 1];
    long-only clips it to [0, 1]. Size: equal risk per coin, scaled by
    target_vol / 30d realised vol, gross exposure capped at max_gross.
    Positions set at day t's close earn day t+1's return — no look-ahead.
    Costs: `cost` per unit of turnover (taker fee + slippage). Net long
    exposure pays funding at `funding_mult` x BTC's rate, a deliberately
    pessimistic proxy because altcoin funding usually runs above BTC's.
    """
    ret = px.pct_change(fill_method=None)
    sig = sum(np.sign(px / px.shift(lb) - 1) for lb in lookbacks) / len(lookbacks)
    if long_only:
        sig = sig.clip(lower=0)
    vol = ret.rolling(30).std() * np.sqrt(365)
    live = px.notna().sum(axis=1).clip(lower=1)
    w = (sig * (target_vol / vol)).div(live, axis=0) / np.sqrt(0.7)  # ~0.7 avg correlation
    w = w.fillna(0)
    gross = w.abs().sum(axis=1)
    w = w.div((gross / max_gross).clip(lower=1), axis=0)

    pos = w.shift(1).fillna(0)
    pnl = (pos * ret.fillna(0)).sum(axis=1)
    trading = w.diff().abs().sum(axis=1).shift(1).fillna(0) * cost
    fund = funding.reindex(px.index).fillna(funding.mean()) * funding_mult
    carry = pos.sum(axis=1) * fund
    return pnl - trading - carry, pos


def stats(r: pd.Series) -> dict[str, float]:
    r = r.dropna()
    eq = (1 + r).cumprod()
    years = len(r) / 365
    return {
        "CAGR%": round((eq.iloc[-1] ** (1 / years) - 1) * 100, 1),
        "Sharpe": round(r.mean() / r.std() * np.sqrt(365), 2),
        "MaxDD%": round((eq / eq.cummax() - 1).min() * 100, 1),
        "x": round(eq.iloc[-1], 2),
    }


def main() -> None:
    px, funding = load_prices(), load_funding()
    start = "2018-01-01"

    r, pos = backtest(px, funding)
    r = r[start:]
    btc = px["BTC"].pct_change()[start:]
    print("== Recommended config: long-only, lookbacks (20,60,120), max 2x ==")
    for label, sl in [
        ("full 2018+", slice(None)),
        ("in-sample 2018-21", slice(None, "2021")),
        ("OUT-OF-SAMPLE 2022+", slice(SPLIT, None)),
    ]:
        print(f"{label:22s} strategy {stats(r[sl])}   BTC buy&hold {stats(btc[sl])}")
    g = pos[start:].abs().sum(axis=1)
    print(
        f"gross exposure: mean {g.mean():.2f}x, max {g.max():.2f}x; worst day {r.min() * 100:.1f}%"
    )
    yearly = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1) * 100
    print("calendar years %:", yearly.round(1).to_dict())

    print("\n== Robustness: every variant, cost 0.15%/turnover, funding 2x BTC ==")
    rows = []
    for lbs in [(10, 20, 40), (20, 60, 120), (30, 90, 180), (50, 100, 200), (20,), (60,), (120,)]:
        for lo in (True, False):
            rr, _ = backtest(
                px, funding, lookbacks=lbs, long_only=lo, target_vol=0.4, max_gross=1.0
            )
            rr = rr[start:]
            rows.append(
                {
                    "lookbacks": lbs,
                    "long_only": lo,
                    "Sharpe_all": stats(rr)["Sharpe"],
                    "Sharpe_IS": stats(rr[:"2021"])["Sharpe"],
                    "Sharpe_OOS": stats(rr[SPLIT:])["Sharpe"],
                    "CAGR_OOS%": stats(rr[SPLIT:])["CAGR%"],
                    "MaxDD%": stats(rr)["MaxDD%"],
                }
            )
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n== Leverage: same signal, larger risk budget ==")
    for tv, cap in [(0.4, 1.0), (0.6, 2.0), (0.8, 2.0), (1.2, 3.0)]:
        rr, p = backtest(px, funding, target_vol=tv, max_gross=cap)
        rr = rr[start:]
        print(
            f"max {cap:.0f}x  full {stats(rr)}  OOS {stats(rr[SPLIT:])}  "
            f"peak exposure {p[start:].abs().sum(axis=1).max():.2f}x"
        )

    print("\n== Stress: double costs (0.30%) and 3x funding ==")
    rr, _ = backtest(px, funding, cost=0.003, funding_mult=3.0)
    print("full", stats(rr[start:]), " OOS", stats(rr[SPLIT:]))


if __name__ == "__main__":
    main()

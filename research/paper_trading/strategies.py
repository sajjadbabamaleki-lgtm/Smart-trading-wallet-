"""Target weights for the EXP-007 candidate portfolio.

Every function takes wide daily frames indexed by UTC day (a row's values are
known at that day's close) and returns weights to hold from that close to the
next one. Nothing reads a row later than the one it decides for.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TA_COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "LINK", "LTC", "AVAX"]
SLEEVE_WEIGHTS = {"crash": 0.25, "trend": 0.25, "ml": 0.5}
MIN_AGE_DAYS = 60
ML_FEATURES = ["r1", "r3", "r7", "r14", "r30", "r60", "vol7", "vol30", "vchg", "f1", "f7", "ma50"]


def liquid_universe(close: pd.DataFrame, notional: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Top-N coins by 30-day mean notional volume, listed at least 60 days."""
    liq = notional.rolling(30, min_periods=20).mean()
    age = close.notna().cumsum()
    return liq.where(age >= MIN_AGE_DAYS).rank(axis=1, ascending=False) <= top_n


def crash_weights(
    close: pd.DataFrame,
    notional: pd.DataFrame,
    drop: float = 0.12,
    hold: int = 3,
    size: float = 0.10,
    top_n: int = 20,
) -> pd.DataFrame:
    """Buy a liquid coin after a one-day drop worse than `drop`; hold `hold` days."""
    ret = close.pct_change(fill_method=None)
    events = (ret < -drop) & liquid_universe(close, notional, top_n)
    w = events.astype(float).rolling(hold, min_periods=1).max() * size
    return w.div(w.sum(axis=1).clip(lower=1.0), axis=0)


def _rsi_free_trend_signals(bars: pd.DataFrame) -> pd.DataFrame:
    """Six long-only trend rules from EXP-005, each 0 or 1."""
    c, h, lo = bars["close"], bars["high"], bars["low"]
    out = {}
    tenkan = (h.rolling(9).max() + lo.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + lo.rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((h.rolling(52).max() + lo.rolling(52).min()) / 2).shift(26)
    out["ichimoku"] = ((c > span_a) & (c > span_b) & (tenkan > kijun)).astype(float)
    ma, sd = c.rolling(20).mean(), c.rolling(20).std()
    brk = pd.Series(np.where(c > ma + 2 * sd, 1.0, np.where(c < ma, 0.0, np.nan)), index=c.index)
    out["bollinger_breakout"] = brk.ffill().fillna(0.0)
    out["ema_50_200"] = (c.ewm(span=50).mean() > c.ewm(span=200).mean()).astype(float)
    macd = c.ewm(span=12).mean() - c.ewm(span=26).mean()
    out["macd"] = (macd > macd.ewm(span=9).mean()).astype(float)
    tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 10).mean()
    mid = (h + lo) / 2
    st = np.where(
        c > (mid + 3 * atr).shift(), 1.0, np.where(c < (mid - 3 * atr).shift(), 0.0, np.nan)
    )
    out["supertrend"] = pd.Series(st, index=c.index).ffill().fillna(0.0)
    don = np.where(
        c > h.rolling(20).max().shift(),
        1.0,
        np.where(c < lo.rolling(20).min().shift(), 0.0, np.nan),
    )
    out["donchian"] = pd.Series(don, index=c.index).ffill().fillna(0.0)
    return pd.DataFrame(out)


def trend_weights(
    bars_4h: dict[str, pd.DataFrame], bars_1d: dict[str, pd.DataFrame], days: pd.DatetimeIndex
) -> pd.DataFrame:
    """EXP-006 indicator ensemble: mean of six rules on 4h and 1d, vol-scaled."""
    cols = {}
    for coin in TA_COINS:
        if coin not in bars_1d or coin not in bars_4h:
            continue
        per_tf = []
        for bars in (bars_4h[coin], bars_1d[coin]):
            sig = _rsi_free_trend_signals(bars).mean(axis=1)
            # A bar is keyed by its open time; the last bar opening on day d
            # closes at d's daily close, so .last() is known at that close.
            per_tf.append(sig.resample("1D").last().reindex(days).ffill())
        sig = pd.concat(per_tf, axis=1).mean(axis=1).fillna(0.0)
        r = bars_1d[coin]["close"].pct_change().reindex(days)
        vol = r.rolling(30).std() * np.sqrt(365)
        cols[coin] = (sig * (0.5 / vol)).clip(upper=1.5).fillna(0.0) / len(TA_COINS)
    return pd.DataFrame(cols, index=days).fillna(0.0)


def ml_features(
    close: pd.DataFrame, notional: pd.DataFrame, funding: pd.DataFrame, universe: pd.DataFrame
) -> pd.DataFrame:
    """Long-format feature table (day, coin) exactly as trained in EXP-007."""
    ret = close.pct_change(fill_method=None).clip(-0.95, 3)
    feat: dict[str, pd.DataFrame] = {}
    for lb in (1, 3, 7, 14, 30, 60):
        feat[f"r{lb}"] = close / close.shift(lb) - 1
    for lb in (7, 30):
        feat[f"vol{lb}"] = ret.rolling(lb).std()
    feat["vchg"] = notional.rolling(3).mean() / notional.rolling(30).mean()
    feat["f1"] = funding
    feat["f7"] = funding.rolling(7).mean()
    feat["ma50"] = close / close.rolling(50).mean() - 1
    for k in list(feat):
        feat[k + "_rk"] = feat[k].where(universe).rank(axis=1, pct=True)
    x = pd.concat({k: v.where(universe) for k, v in feat.items()}, axis=1).stack(future_stack=True)
    mkt = ret.where(universe).mean(axis=1)
    x["mkt1"] = x.index.get_level_values(0).map(mkt)
    return x.dropna(subset=["r1"])


def ml_weights(predictions: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """Market-neutral, rank-weighted and inverse-vol scaled, gross 1x."""
    vol = close.pct_change(fill_method=None).rolling(30).std().reindex(predictions.index)
    s = predictions.rank(axis=1, pct=True) - 0.5
    w = s / vol
    return w.div(w.abs().sum(axis=1), axis=0).fillna(0.0)


def combine(sleeves: dict[str, pd.DataFrame], leverage: float) -> pd.DataFrame:
    cols = sorted(set().union(*(s.columns for s in sleeves.values())))
    idx = next(iter(sleeves.values())).index
    total = pd.DataFrame(0.0, index=idx, columns=cols)
    for name, w in sleeves.items():
        total = total.add(w.reindex(index=idx, columns=cols).fillna(0.0) * SLEEVE_WEIGHTS[name])
    return total * leverage

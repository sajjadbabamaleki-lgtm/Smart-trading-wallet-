"""Train the EXP-007 ML sleeve on Binance history and save it for paper trading.

Input: the wide daily panels built from data.binance.vision in EXP-004
(C.pkl close, V.pkl quote volume, F.pkl daily funding), all USDT-M perps.
Features are scale-free, so a model trained on Binance symbols applies to
Hyperliquid coins unchanged.

    python -m research.paper_trading.train_model <dir-with-C.pkl-V.pkl-F.pkl>
"""

from __future__ import annotations

import sys
from pathlib import Path

import lightgbm as lgb
import pandas as pd

from research.paper_trading.strategies import liquid_universe, ml_features

MODEL_PATH = Path(__file__).resolve().parent / "model" / "ml_lgbm.txt"


def main(data_dir: Path) -> None:
    close = pd.read_pickle(data_dir / "C.pkl")  # noqa: S301 - locally built research panel
    notional = pd.read_pickle(data_dir / "V.pkl").reindex_like(close)  # noqa: S301
    funding = pd.read_pickle(data_dir / "F.pkl").reindex_like(close).fillna(0.0)  # noqa: S301
    universe = liquid_universe(close, notional, top_n=30)
    x = ml_features(close, notional, funding, universe)
    ret = close.pct_change(fill_method=None).clip(-0.95, 3)
    target = (ret.shift(-1) - funding.shift(-1)).where(universe).rank(axis=1, pct=True)
    y = target.stack(future_stack=True).reindex(x.index)
    ok = y.notna()
    model = lgb.LGBMRegressor(
        n_estimators=300,
        learning_rate=0.03,
        num_leaves=15,
        min_child_samples=200,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        random_state=7,
        verbose=-1,
    )
    model.fit(x[ok], y[ok])
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    model.booster_.save_model(str(MODEL_PATH))
    last = x.index.get_level_values(0)[ok.to_numpy()].max()
    print(f"trained on {int(ok.sum())} rows through {last:%Y-%m-%d}; saved {MODEL_PATH}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

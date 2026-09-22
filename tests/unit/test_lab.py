"""The strategy lab: rules the search must not be able to bend."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from services.analyst.candles import Candle
from services.analyst.simulator import BacktestConfig, Simulator
from services.lab import data, registry
from services.lab.engine import run
from services.lab.strategies import (
    CATALOGUE,
    CrossSectionalFunding,
    CrossSectionalMomentum,
    DonchianEnsemble,
    Enter,
    Held,
    MoveStop,
    Strategy,
    TrendTrailing,
    _rolling_extremes,
)
from services.trader.venue import Direction

STEP = timedelta(hours=4)
START = datetime(2024, 6, 3, tzinfo=UTC)  # a Monday


def series(
    n: int, drift: float, phase: float = 0.0, start: float = 100.0, wave: float = 0.03
) -> list[Candle]:
    candles, previous = [], start
    for i in range(n):
        close = start * math.exp(drift * i + wave * math.sin(i / 20 + phase))
        high, low = max(previous, close) * 1.004, min(previous, close) * 0.996
        candles.append(Candle(START + STEP * i, previous, high, low, close, 1.0))
        previous = close
    return candles


def dataset(n: int = 4800, symbols: tuple[str, ...] | None = None) -> data.Dataset:
    drifts = [0.0006, -0.0004, 0.0002, 0.0008, -0.0007, 0.0, 0.0003, -0.0002, 0.0005, -0.0001]
    names = symbols or tuple(f"A{k}" for k in range(6))
    candles = {name: series(n, drifts[k], phase=k) for k, name in enumerate(names)}
    funding = {
        s: {c.open_time + timedelta(hours=h): 0.00001 for c in cs for h in range(4)}
        for s, cs in candles.items()
    }
    return data.Dataset(candles=candles, funding=funding)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("highest", [True, False])
def test_rolling_extremes_match_a_brute_force_scan(highest: bool) -> None:
    values = [math.sin(i * 0.7) * 10 + i % 5 for i in range(300)]
    fast = _rolling_extremes(values, 17, highest=highest)
    pick = max if highest else min
    for i, value in enumerate(fast):
        expected = pick(values[i - 17 : i]) if i >= 17 else None
        assert value == expected


def test_stops_only_tighten() -> None:
    sim = Simulator(BacktestConfig())
    bar = series(2, 0.0)[1]
    sim.schedule_entry(Direction.LONG, bar.open * 0.9, None)
    sim.open_candle(bar)
    assert sim.position is not None
    assert sim.move_stop(bar.open * 0.95)
    assert not sim.move_stop(bar.open * 0.92)  # looser: refused
    assert sim.position.stop == pytest.approx(bar.open * 0.95)


def test_a_position_can_be_reversed_at_one_candle() -> None:
    sim = Simulator(BacktestConfig())
    bars = series(3, 0.0)
    sim.schedule_entry(Direction.LONG, bars[1].open * 0.8, None)
    sim.open_candle(bars[1])
    sim.schedule_exit()
    sim.schedule_entry(Direction.SHORT, bars[2].open * 1.2, None)
    sim.open_candle(bars[2])
    assert sim.position is not None and sim.position.direction is Direction.SHORT
    assert len(sim.trades) == 1


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class AlwaysLong(Strategy):
    name = "always-long"
    summary = "test double"
    source = "test"

    def decide(self, time: datetime, index: dict[str, int], held: dict[str, Held | None]) -> Any:  # noqa: ARG002
        return [
            (s, Enter(Direction.LONG, self.candles[s][i].close * 0.5))
            for s, i in index.items()
            if held[s] is None
        ]


def test_engine_accounting_and_window_bounds() -> None:
    ds = dataset(1200)
    start, end = START + STEP * 200, START + STEP * 1000
    result = run(AlwaysLong(), ds, start=start, end=end)

    assert all(start <= t.entry_time < end for t in result.trades)
    assert all(t.exit_reason == "end of window" for t in result.trades)
    final = 10_000 * (1 + result.full.total_return)
    assert final == pytest.approx(10_000 + sum(t.pnl for t in result.trades))
    assert sum(result.trades_by_asset.values()) == len(result.trades) == len(ds.candles)


def test_every_catalogue_strategy_runs_and_uses_only_the_window() -> None:
    ds = dataset()
    start, end = ds.start + data.DEV_WARMUP, data.HOLDOUT_START
    for name, cls in CATALOGUE.items():
        result = run(cls(), ds, start=start, end=end)
        assert result.strategy == name
        assert all(start <= t.entry_time < end and t.exit_time <= end for t in result.trades)
        assert result.observations > 0


def test_trailing_strategy_only_ever_tightens_its_stop() -> None:
    ds = dataset()
    strategy = TrendTrailing()
    strategy.prepare(ds.candles)
    candles = ds.candles["A3"]  # strong uptrend
    entry = 700
    held = Held(Direction.LONG, entry, candles[entry].close * 0.8)
    stops = []
    for i in range(entry + 1, entry + 200):
        for _, action in strategy.decide(candles[i].open_time, {"A3": i}, {"A3": held}):
            assert isinstance(action, MoveStop)
            stops.append(action.stop)
    # The proposed trail follows the best close; the simulator keeps the maximum.
    assert max(stops) > stops[0]


def test_donchian_goes_long_in_a_persistent_uptrend() -> None:
    candles = {"UP": series(1200, 0.006, wave=0.0)}  # closes clear the prior 0.4% wicks
    strategy = DonchianEnsemble()
    strategy.prepare(candles)
    for i in range(500, 1200, 50):  # every channel is broken upward, at every lookback
        actions = strategy.decide(candles["UP"][i].open_time, {"UP": i}, {"UP": None})
        assert actions and isinstance(actions[0][1], Enter)
        assert actions[0][1].direction is Direction.LONG


def test_cross_sectional_momentum_trades_only_on_monday_and_ranks_the_ends() -> None:
    ds = dataset()
    strategy = CrossSectionalMomentum()
    strategy.prepare(ds.candles)
    monday_close = next(
        i
        for i, c in enumerate(ds.candles["A0"])
        if i > 500 and (c.open_time + STEP).weekday() == 0 and (c.open_time + STEP).hour == 0
    )
    index = dict.fromkeys(ds.candles, monday_close)
    held = dict.fromkeys(ds.candles)
    actions = strategy.decide(ds.candles["A0"][monday_close].open_time, index, held)
    longs = {s for s, a in actions if isinstance(a, Enter) and a.direction is Direction.LONG}
    shorts = {s for s, a in actions if isinstance(a, Enter) and a.direction is Direction.SHORT}
    assert len(longs) == len(shorts) == 3
    assert "A3" in longs and "A4" in shorts
    assert strategy.decide(ds.candles["A0"][monday_close + 1].open_time, index, held) == []


def test_cross_sectional_funding_shorts_the_highest_funding_and_ignores_the_future() -> None:
    ds = dataset()
    strategy = CrossSectionalFunding()
    monday_close = next(
        i
        for i, c in enumerate(ds.candles["A0"])
        if i > 500 and (c.open_time + STEP).weekday() == 0 and (c.open_time + STEP).hour == 0
    )
    closes_at = ds.candles["A0"][monday_close].open_time + STEP
    # A0 has the highest past funding, A5 the lowest; after the close the order flips.
    strategy.funding = {
        s: {t: (k if t < closes_at else -k) / 100_000 for t in ds.funding[s]}
        for k, s in zip(range(6, 0, -1), sorted(ds.candles), strict=True)
    }
    strategy.prepare(ds.candles)
    index = dict.fromkeys(ds.candles, monday_close)
    actions = strategy.decide(closes_at - STEP, index, dict.fromkeys(ds.candles))
    shorts = {s for s, a in actions if isinstance(a, Enter) and a.direction is Direction.SHORT}
    longs = {s for s, a in actions if isinstance(a, Enter) and a.direction is Direction.LONG}
    assert shorts == {"A0", "A1", "A2"} and longs == {"A3", "A4", "A5"}
    assert strategy.decide(closes_at, index, dict.fromkeys(ds.candles)) == []


# ---------------------------------------------------------------------------
# Registry and Deflated Sharpe
# ---------------------------------------------------------------------------


def test_expected_max_sharpe_rises_with_the_number_of_trials() -> None:
    sharpes = [0.01, 0.02, -0.01, 0.03]
    assert registry.expected_max_sharpe(sharpes, 1) == 0.0
    few = registry.expected_max_sharpe(sharpes, 5)
    many = registry.expected_max_sharpe(sharpes, 50)
    assert 0 < few < many


def test_deflation_lowers_the_probability() -> None:
    plain = registry.deflated_sharpe(0.03, 2000, 0.0, 3.0, 0.0)
    deflated = registry.deflated_sharpe(0.03, 2000, 0.0, 3.0, 0.02)
    assert deflated < plain
    # With no skew and normal tails, the formula reduces to Φ(SR·√(T-1)/√(1+SR²/2)).
    expected = math.erf(0.03 * math.sqrt(1999) / math.sqrt(1 + 0.03**2 / 2) / math.sqrt(2))
    assert plain == pytest.approx((1 + expected) / 2)


def test_trials_are_counted_by_name_and_the_holdout_is_once(tmp_path: Path) -> None:
    ds = dataset(1200)
    path = tmp_path / "trials.jsonl"
    result = run(AlwaysLong(), ds, start=START + STEP * 200, end=START + STEP * 800)
    registry.record(result, "development", path)
    registry.record(result, "development", path)
    entries = registry.load(path)
    assert len(entries) == 2  # both runs are in the log…
    assert list(registry.development_trials(entries)) == ["always-long"]  # …one trial
    assert not registry.holdout_used("always-long", entries)
    registry.record(result, "holdout", path)
    assert registry.holdout_used("always-long", registry.load(path))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_run_list_trials_and_single_holdout(capsys: pytest.CaptureFixture[str]) -> None:
    from services.lab.cli import main  # noqa: PLC0415

    ds = dataset(symbols=data.ASSETS)
    for symbol, candles in ds.candles.items():
        data.save(symbol, candles, ds.funding[symbol])

    assert main(["run", "trend-trailing"]) == 0
    out = capsys.readouterr().out
    assert "Development window" in out and "Deflated Sharpe" in out

    assert main(["trials"]) == 0
    assert "trend-trailing" in capsys.readouterr().out

    assert main(["holdout", "trend-trailing"]) == 0
    assert "Holdout verdict" in capsys.readouterr().out
    assert main(["holdout", "trend-trailing"]) == 1
    assert "already used its holdout" in capsys.readouterr().err

    assert main(["holdout", "xsec-momentum"]) == 1
    assert "development window first" in capsys.readouterr().err

    assert main(["list"]) == 0
    assert "holdout USED" in capsys.readouterr().out


def test_fetch_merges_with_the_cache_so_old_history_is_kept() -> None:
    old = series(100, 0.0)
    data.save("A0", old, {})

    class Info:
        def candles_snapshot(self, *_request: Any) -> Any:
            return [
                {
                    "t": int(c.open_time.timestamp() * 1000),
                    "o": c.open,
                    "h": c.high,
                    "l": c.low,
                    "c": c.close,
                    "v": 1,
                }
                for c in series(160, 0.0)[60:]
            ]

        def funding_history(self, *_request: Any) -> Any:
            return []

    report, failed = data.fetch(Info(), ("A0",), now=START + STEP * 170)
    assert not failed
    assert len(data.load(("A0",)).candles["A0"]) == 160  # 100 cached + 60 new
    assert "160 candles" in report[0]

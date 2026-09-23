"""Binance data and the weekly cross-sectional engine."""

from __future__ import annotations

import io
import math
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from services.lab import binance, registry, xsection
from services.lab.binance import Day, Market

START = datetime(2021, 1, 4, tzinfo=UTC)  # a Monday


def zipped(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("x.csv", text)
    return buffer.getvalue()


def test_klines_parse_with_and_without_a_header() -> None:
    row = "1704067200000,1,2,0.5,1.5,10,1704153599999,15.5,3,1,1,0"
    old = binance.parse_klines(zipped(row + "\n"))
    new = binance.parse_klines(zipped("open_time,open,high,low,close,volume,a,b\n" + row))
    assert old == new
    assert old[0].close == 1.5 and old[0].quote_volume == 15.5


def test_symbols_exclude_stablecoins_indices_and_dated_futures() -> None:
    assert binance.eligible_symbol("BTCUSDT")
    assert binance.eligible_symbol("1000PEPEUSDT")
    assert not binance.eligible_symbol("USDCUSDT")
    assert not binance.eligible_symbol("BTCDOMUSDT")
    assert not binance.eligible_symbol("BTCUSDT_240628")


def test_bucket_listing_follows_pages() -> None:
    pages = {
        "": "<Key>p/a.zip</Key><IsTruncated>true</IsTruncated><NextMarker>p/a.zip</NextMarker>",
        "p/a.zip": "<Key>p/b.zip</Key><IsTruncated>false</IsTruncated>",
    }

    def get(url: str) -> bytes:
        marker = url.split("marker=")[1].split("&", maxsplit=1)[0].replace("%2F", "/")
        return pages[marker].encode()

    assert binance.list_keys("p/", delimiter=False, get=get) == ["p/a.zip", "p/b.zip"]


def test_ols_recovers_known_slopes() -> None:
    x = [[i / 10, (i * 7 % 11) / 10] for i in range(30)]
    y = [0.5 + 2 * a - 3 * b for a, b in x]
    assert xsection.ols(x, y) == pytest.approx([2.0, -3.0], abs=0.01)
    twins = xsection.ols([[a, a] for a, _ in x], [2 * a for a, _ in x])  # collinear
    assert twins == pytest.approx([1.0, 1.0], abs=0.01)  # the ridge splits the weight


def test_rank_scale_bounds_outliers() -> None:
    scaled = xsection.rank_scale([[1.0], [1e9], [5.0]])
    assert [r[0] for r in scaled] == [-0.5, 0.5, 0.0]


def market(n_days: int = 700, coins: int = 30) -> Market:
    """Coins whose trend persists: each drifts at its own constant rate."""
    days, funding = {}, {}
    for k in range(coins):
        drift = (k - coins / 2) / 2000
        rows = []
        for d in range(n_days):
            close = 100 * math.exp(drift * d + 0.02 * math.sin(d / 3 + k))
            volume = 1e6 * (k + 1) * (1.5 + math.sin(d * (k + 1) / 7) + math.cos(d / (k + 2)))
            rows.append(Day(START + timedelta(days=d), close, close, close, close, volume))
        days[f"C{k}USDT"] = rows
        funding[f"C{k}USDT"] = {r.time: 0.0001 for r in rows}
    return Market(days=days, funding=funding)


def test_ctrend_goes_long_the_persistent_winners_and_accounts_for_costs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(xsection, "UNIVERSE_SIZE", 25)
    monkeypatch.setattr(xsection, "MIN_COEFFICIENT_WEEKS", 4)
    result = xsection.run_ctrend(market())
    m = xsection.metrics(result)
    assert m.total_return > 0  # trends persist by construction
    assert result.costs > 0 and result.turnover > 0
    assert all(d.weekday() == 0 for d in result.days[:1])  # first return is a Monday's
    # Dollar neutral with equal funding on both sides: funding nets to about zero.
    assert abs(result.funding) < 0.01


def test_windows_and_metrics() -> None:
    days = [START + timedelta(days=i) for i in range(10)]
    result = xsection.XResult("x", days, [0.01, -0.02] * 5, [0.0] * 10, 0, 0, 0)
    part = result.window(days[2], days[6])
    assert part.days == days[2:6]
    m = xsection.metrics(result)
    assert m.max_drawdown < 0 and m.profit_factor == pytest.approx(0.5)


def test_registry_compares_trials_at_different_frequencies() -> None:
    four_hourly = {"sharpe_per_bar": 0.02, "bars_per_year": 2190}
    daily = {"sharpe_per_bar": 0.02 * math.sqrt(2190 / 365), "bars_per_year": 365}
    legacy = {"sharpe_per_bar": 0.02}
    assert registry.annual_sharpe(four_hourly) == pytest.approx(registry.annual_sharpe(daily))
    assert registry.annual_sharpe(legacy) == pytest.approx(registry.annual_sharpe(four_hourly))


def test_fetch_downloads_klines_then_funding_and_resumes() -> None:
    klines = "".join(
        f"{1704067200000 + d * 86_400_000},1,2,0.5,1.5,10,0,15.5,3,1,1,0\n" for d in range(40)
    )
    served: list[str] = []

    def get(url: str) -> bytes:
        served.append(url)
        if "?" in url:
            if "delimiter" in url:
                return f"<Prefix>{binance.KLINES_PREFIX}AUSDT/</Prefix>".encode()
            if "fundingRate" in url:
                key = f"{binance.FUNDING_PREFIX}AUSDT/AUSDT-fundingRate-2024-01.zip"
                return f"<Key>{key}</Key>".encode()
            return b"<Key>data/futures/um/monthly/klines/AUSDT/1d/AUSDT-1d-2024-01.zip</Key>"
        if "fundingRate" in url:
            return zipped("1704067200000,8,0.0001\n1704096000000,8,0.0002\n")
        return zipped(klines)

    ok, failed = binance.fetch(get=get, workers=1)
    assert ok == ["AUSDT"] and not failed
    market = binance.load()
    assert market.funding["AUSDT"][START.replace(year=2024, month=1, day=1)] == pytest.approx(
        0.0003
    )
    before = len(served)
    binance.fetch(get=get, workers=1)
    assert len(served) == before + 1  # only the symbol listing: everything is cached

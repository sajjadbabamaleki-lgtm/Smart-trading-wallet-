"""The analyst: indicators, strategy, calendar, news filter and backtest."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from services.analyst import calendar
from services.analyst.analyst import analyse_candles
from services.analyst.backtest import (
    BacktestConfig,
    _max_drawdown,
    probabilistic_sharpe,
    run_backtest,
)
from services.analyst.candles import (
    Candle,
    CandleError,
    closed_only,
    load_binance_csv,
    validate_series,
)
from services.analyst.indicators import atr, ema, sma, trailing_return
from services.analyst.news import (
    Assessment,
    Category,
    ClassificationError,
    Headline,
    Implication,
    NewsCheck,
    Relevance,
    Severity,
    check_news,
    classify,
    fetch_headlines,
    parse_feed,
    veto_reasons,
)
from services.analyst.strategy import InsufficientHistoryError, StrategyParams, TrendIndicators
from services.trader.venue import Direction

START = datetime(2025, 1, 1, tzinfo=UTC)
STEP = timedelta(hours=4)


def make_candles(closes: list[float], *, wiggle: float = 0.005) -> list[Candle]:
    candles = []
    previous = closes[0]
    for i, close in enumerate(closes):
        high = max(previous, close) * (1 + wiggle)
        low = min(previous, close) * (1 - wiggle)
        candles.append(Candle(START + STEP * i, previous, high, low, close, 1000.0))
        previous = close
    return candles


def trend(n: int, start: float, per_bar: float) -> list[float]:
    return [start * (1 + per_bar) ** i for i in range(n)]


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------


class TestIndicators:
    def test_sma(self) -> None:
        assert sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]

    def test_ema_is_seeded_with_the_sma(self) -> None:
        # alpha = 2 / (3 + 1) = 0.5; seed = mean(1, 2, 3) = 2
        assert ema([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]

    def test_atr_uses_wilder_smoothing(self) -> None:
        candles = [
            Candle(START, 10, 11, 9, 10, 1),  # TR 2
            Candle(START + STEP, 10, 12, 10, 11, 1),  # TR 2
            Candle(START + STEP * 2, 11, 15, 11, 14, 1),  # TR 4
        ]
        # seed = (2 + 2) / 2 = 2; then (2 * 1 + 4) / 2 = 3
        assert atr(candles, 2) == [None, 2.0, 3.0]

    def test_true_range_includes_gaps(self) -> None:
        candles = [Candle(START, 10, 10.5, 9.5, 10, 1), Candle(START + STEP, 13, 13.5, 12.5, 13, 1)]
        # gap up: TR = high - previous close = 3.5, not high - low = 1
        assert atr(candles, 1)[1] == 3.5

    def test_trailing_return(self) -> None:
        assert trailing_return([100, 110, 121], 1) == [None, pytest.approx(0.1), pytest.approx(0.1)]


# ---------------------------------------------------------------------------
# Candles
# ---------------------------------------------------------------------------


class TestCandles:
    def test_binance_csv_with_header_and_microseconds(self, tmp_path: Path) -> None:
        path = tmp_path / "SOLUSDT-4h.csv"
        millis = int(START.timestamp() * 1000)
        micros = int((START + STEP).timestamp() * 1_000_000)
        path.write_text(
            "open_time,open,high,low,close,volume\n"
            f"{millis},100,110,90,105,1\n"
            f"{micros},105,112,100,110,1\n"
        )
        candles = validate_series(load_binance_csv([path]), "4h")
        assert [c.open_time for c in candles] == [START, START + STEP]

    def test_gaps_are_refused(self) -> None:
        candles = make_candles([1, 2, 3])
        with pytest.raises(CandleError, match="gap"):
            validate_series([candles[0], candles[2]], "4h")

    def test_the_forming_candle_is_dropped(self) -> None:
        candles = make_candles([1, 2, 3])
        now = candles[-1].open_time + timedelta(hours=1)
        assert len(closed_only(candles, "4h", now)) == 2

    def test_inconsistent_candle_is_rejected(self) -> None:
        with pytest.raises(CandleError):
            Candle(START, 10, 9, 8, 10, 1)


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


PARAMS = StrategyParams()
WARMUP = PARAMS.warmup_bars("4h")


class TestStrategy:
    def test_uptrend_proposes_a_long_with_atr_stop_and_2r_target(self) -> None:
        candles = make_candles(trend(WARMUP + 10, 100, 0.002))
        signal = TrendIndicators(candles, "4h", PARAMS).signal(len(candles) - 1)
        assert signal.direction is Direction.LONG
        assert signal.score == 1.0
        assert signal.stop_loss is not None and signal.take_profit is not None
        assert signal.close - signal.stop_loss == pytest.approx(2 * signal.atr)
        assert signal.take_profit - signal.close == pytest.approx(4 * signal.atr)

    def test_downtrend_proposes_a_short(self) -> None:
        candles = make_candles(trend(WARMUP + 10, 100, -0.002))
        signal = TrendIndicators(candles, "4h", PARAMS).signal(len(candles) - 1)
        assert signal.direction is Direction.SHORT
        assert signal.stop_loss is not None and signal.stop_loss > signal.close

    def test_shorts_can_be_disabled(self) -> None:
        candles = make_candles(trend(WARMUP + 10, 100, -0.002))
        params = StrategyParams(allow_short=False)
        signal = TrendIndicators(candles, "4h", params).signal(len(candles) - 1)
        assert signal.direction is None
        assert "shorts are disabled" in signal.reasons[0]

    def test_mixed_votes_mean_no_trade(self) -> None:
        # Long uptrend, then a one-week drop: short-horizon votes turn down,
        # long-horizon votes still point up.
        closes = trend(WARMUP, 100, 0.002) + trend(42, 100 * 1.002**WARMUP, -0.004)
        candles = make_candles(closes)
        signal = TrendIndicators(candles, "4h", PARAMS).signal(len(candles) - 1)
        assert signal.direction is None
        assert abs(signal.score) < PARAMS.entry_threshold

    def test_crowded_funding_blocks_the_long(self) -> None:
        candles = make_candles(trend(WARMUP + 10, 100, 0.002))
        hourly = 1.5 / (24 * 365)  # 150% a year
        signal = TrendIndicators(candles, "4h", PARAMS).signal(
            len(candles) - 1, funding_hourly=hourly
        )
        assert signal.direction is None
        assert "crowded" in signal.reasons[-1]

    def test_short_history_is_refused(self) -> None:
        candles = make_candles(trend(WARMUP - 1, 100, 0.002))
        with pytest.raises(InsufficientHistoryError):
            TrendIndicators(candles, "4h", PARAMS).signal(len(candles) - 1)


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


class TestCalendar:
    def test_fomc_statement_is_2pm_eastern(self) -> None:
        october = next(e for e in calendar.EVENTS if e.at.month == 10 and "FOMC" in e.name)
        assert october.at.astimezone(UTC) == datetime(2026, 10, 28, 18, 0, tzinfo=UTC)  # EDT
        december = next(e for e in calendar.EVENTS if e.at.month == 12 and "FOMC" in e.name)
        assert december.at.astimezone(UTC) == datetime(2026, 12, 9, 19, 0, tzinfo=UTC)  # EST

    def test_window_around_an_event_blocks(self) -> None:
        statement = datetime(2026, 10, 28, 18, 0, tzinfo=UTC)
        assert calendar.check(statement - timedelta(hours=11)).blocking is not None
        assert calendar.check(statement + timedelta(hours=2)).blocking is not None
        assert calendar.check(statement - timedelta(hours=13)).blocking is None
        assert calendar.check(statement + timedelta(hours=4)).blocking is None

    def test_calendar_goes_stale_after_its_last_year(self) -> None:
        assert not calendar.check(datetime(2026, 11, 1, tzinfo=UTC)).stale
        assert calendar.check(datetime(2027, 1, 2, tzinfo=UTC)).stale


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Solana validators halt network after consensus bug</title>
<link>https://example.com/a</link><pubDate>Tue, 22 Sep 2026 09:00:00 +0000</pubDate></item>
<item><title>Old story</title><pubDate>Mon, 14 Sep 2026 09:00:00 +0000</pubDate></item>
<item><title>No date</title></item>
</channel></rss>"""
ATOM_FEED = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>SOL ETF approved</title><link href="https://example.com/b"/>
<updated>2026-09-22T10:00:00Z</updated></entry></feed>"""


def _assessment(**overrides: Any) -> Assessment:
    fields = {
        "index": 0,
        "relevance": Relevance.DIRECT,
        "implication": Implication.BEARISH,
        "severity": Severity.HIGH,
        "category": Category.REGULATION_LEGAL,
    }
    fields.update(overrides)
    return Assessment(**fields)


class FakeClaude:
    """Stands in for anthropic.Anthropic(); records the request it was sent."""

    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.requests: list[dict[str, Any]] = []
        self._response = SimpleNamespace(
            stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)]
        )
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return self._response


class TestNews:
    def test_rss_and_atom_are_parsed_and_undated_items_skipped(self) -> None:
        rss = parse_feed(RSS, "example.com")
        assert [h.title for h in rss] == [
            "Solana validators halt network after consensus bug",
            "Old story",
        ]
        atom = parse_feed(ATOM_FEED, "example.com")
        assert atom[0].published == datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
        assert atom[0].link == "https://example.com/b"

    def test_entity_expansion_is_refused(self) -> None:
        bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><x>&a;</x></rss>'
        with pytest.raises(ValueError):  # defusedxml's EntitiesForbidden
            parse_feed(bomb, "evil")

    def test_only_recent_headlines_are_kept_and_failed_feeds_reported(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "down.example":
                return httpx.Response(503)
            return httpx.Response(200, content=RSS)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            headlines, errors = fetch_headlines(
                ["https://ok.example/rss", "https://down.example/rss"], now=NOW, client=client
            )
        assert [h.title for h in headlines] == [
            "Solana validators halt network after consensus bug"
        ]
        assert len(errors) == 1 and "down.example" in errors[0]

    def test_classification_request_uses_schema_effort_and_fallback(self) -> None:
        headline = Headline("SOL ETF approved", "x", NOW)
        reply = {"assessments": [_assessment(implication=Implication.BULLISH).model_dump()]}
        claude = FakeClaude(json.dumps(reply))
        [result] = classify([headline], "SOL", client=claude)
        assert result.implication is Implication.BULLISH
        request = claude.requests[0]
        assert request["model"] == "claude-opus-5"
        assert request["fallbacks"] == "default"
        assert request["betas"] == ["server-side-fallback-2026-07-01"]
        assert request["output_config"]["effort"] == "low"
        assert request["output_config"]["format"]["type"] == "json_schema"
        assert "SOL ETF approved" in request["messages"][0]["content"]

    def test_refusal_and_malformed_output_raise(self) -> None:
        headline = Headline("x", "x", NOW)
        with pytest.raises(ClassificationError, match="declined"):
            classify([headline], "SOL", client=FakeClaude("", stop_reason="refusal"))
        with pytest.raises(ClassificationError, match="schema"):
            classify([headline], "SOL", client=FakeClaude('{"assessments": [{"index": 0}]}'))

    def test_opposing_high_severity_news_vetoes(self) -> None:
        headlines = [Headline("SEC sues Solana Foundation", "x", NOW)]
        assert veto_reasons(headlines, [_assessment()], Direction.LONG)
        assert not veto_reasons(headlines, [_assessment()], Direction.SHORT)

    def test_hack_or_outage_vetoes_either_direction(self) -> None:
        headlines = [Headline("Network halted", "x", NOW)]
        outage = _assessment(category=Category.NETWORK_OUTAGE, implication=Implication.BEARISH)
        assert veto_reasons(headlines, [outage], Direction.SHORT)

    @pytest.mark.parametrize(
        "overrides",
        [
            {"severity": Severity.MEDIUM},
            {"relevance": Relevance.NONE},
            {"category": Category.PRICE_COMMENTARY},
        ],
    )
    def test_minor_irrelevant_or_commentary_news_does_not_veto(
        self, overrides: dict[str, Any]
    ) -> None:
        headlines = [Headline("x", "x", NOW)]
        assert not veto_reasons(headlines, [_assessment(**overrides)], Direction.LONG)

    def test_without_a_key_news_is_unavailable_not_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        with httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=RSS))
        ) as http:
            result = check_news(
                "SOL", Direction.LONG, now=NOW, feeds=["https://a/"], http_client=http
            )
        assert not result.available
        assert "ANTHROPIC_API_KEY" in result.notes[-1]


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


class TestAnalysis:
    candles = make_candles(trend(WARMUP + 10, 100, 0.002))

    def _run(self, now: datetime, news: NewsCheck | None) -> Any:
        return analyse_candles(
            self.candles,
            symbol="SOL",
            interval="4h",
            now=now,
            funding_hourly=None,
            news_checker=(lambda *_: news) if news is not None else None,
        )

    def test_all_checks_passing_allows_automation(self) -> None:
        analysis = self._run(NOW, NewsCheck(available=True))
        assert analysis.direction is Direction.LONG
        assert analysis.may_auto_execute

    def test_unchecked_news_blocks_automation_but_keeps_the_proposal(self) -> None:
        analysis = self._run(NOW, None)
        assert analysis.direction is Direction.LONG
        assert not analysis.may_auto_execute

    def test_news_veto_removes_the_trade(self) -> None:
        analysis = self._run(NOW, NewsCheck(available=True, vetoes=["hack"]))
        assert analysis.direction is None

    def test_macro_event_window_removes_the_trade(self) -> None:
        cpi = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
        analysis = self._run(cpi, NewsCheck(available=True))
        assert analysis.direction is None
        assert "CPI" in analysis.vetoes[0]


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


def _backtest(closes: list[float], **config: Any) -> Any:
    return run_backtest(make_candles(closes), BacktestConfig(**config))


class TestBacktest:
    def test_equity_equals_initial_plus_every_trades_pnl(self) -> None:
        # Up, down, up: several entries and exits of both kinds.
        closes = (
            trend(WARMUP + 200, 100, 0.002)
            + trend(300, 100 * 1.002 ** (WARMUP + 199), -0.002)
            + trend(300, 60, 0.002)
        )
        result = _backtest(closes)
        assert result.trades
        final = 10_000 * (1 + result.full.total_return)
        assert final == pytest.approx(10_000 + sum(t.pnl for t in result.trades), rel=1e-9)

    def test_entry_fills_at_the_next_open_never_the_signal_close(self) -> None:
        closes = trend(WARMUP + 50, 100, 0.002)
        candles = make_candles(closes)
        result = run_backtest(candles, BacktestConfig(slippage=0))
        first = result.trades[0]
        signal_bar = next(i for i, c in enumerate(candles) if c.open_time == first.entry_time) - 1
        assert first.entry_price == candles[signal_bar + 1].open
        assert signal_bar >= WARMUP - 1

    def test_stop_is_assumed_first_when_a_candle_touches_both(self) -> None:
        closes = trend(WARMUP + 5, 100, 0.002)
        candles = make_candles(closes)
        last = candles[-1]
        # One huge candle spanning any plausible stop and target.
        candles.append(
            Candle(last.open_time + STEP, last.close, last.close * 2, last.close / 2, last.close, 1)
        )
        candles.append(
            Candle(last.open_time + STEP * 2, last.close, last.close, last.close, last.close, 1)
        )
        result = run_backtest(candles, BacktestConfig())
        assert result.trades[0].exit_reason == "stop"

    def test_gap_through_the_stop_fills_at_the_open(self) -> None:
        candles = make_candles(trend(WARMUP + 5, 100, 0.002))
        last = candles[-1]
        gap_open = last.close * 0.5
        candles.append(
            Candle(last.open_time + STEP, gap_open, gap_open, gap_open * 0.99, gap_open, 1)
        )
        result = run_backtest(candles, BacktestConfig(slippage=0))
        stopped = result.trades[0]
        assert stopped.exit_reason == "stop"
        assert stopped.exit_price == gap_open
        assert stopped.r_multiple < -1  # a gap costs more than the planned risk

    def test_costs_are_charged(self) -> None:
        result = _backtest(trend(WARMUP + 300, 100, 0.002))
        assert result.full.fees > 0
        assert result.full.funding > 0  # longs pay the default positive funding

    def test_losses_are_bounded_by_the_risk_budget(self) -> None:
        # A choppy series: entries get stopped out, never for much more than 1R.
        closes = [100 * (1 + 0.08 * math.sin(i / 15)) * 1.0005**i for i in range(WARMUP + 1500)]
        result = _backtest(closes)
        stops = [t for t in result.trades if t.exit_reason == "stop"]
        assert stops
        assert min(t.r_multiple for t in stops) > -1.3

    def test_too_little_data_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not enough candles"):
            _backtest(trend(WARMUP, 100, 0.002))

    def test_few_trades_are_flagged(self) -> None:
        result = _backtest(trend(WARMUP + 50, 100, 0.002))
        assert any("too few" in w for w in result.warnings)


class TestStatistics:
    def test_probabilistic_sharpe_of_noise_is_near_half(self) -> None:
        noise = [0.01 * math.sin(i * 1.7) for i in range(1000)]
        assert 0.3 < probabilistic_sharpe(noise) < 0.7

    def test_probabilistic_sharpe_of_steady_gains_is_near_one(self) -> None:
        gains = [0.001 + 0.0005 * math.sin(i) for i in range(500)]
        assert probabilistic_sharpe(gains) > 0.99

    def test_max_drawdown(self) -> None:
        assert _max_drawdown([100, 120, 90, 130]) == pytest.approx(-0.25)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class FakeInfo:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles

    def candles_snapshot(self, *_request: Any) -> Any:
        return [
            {
                "t": int(c.open_time.timestamp() * 1000),
                "o": str(c.open),
                "h": str(c.high),
                "l": str(c.low),
                "c": str(c.close),
                "v": str(c.volume),
            }
            for c in self.candles
        ]

    def meta_and_asset_ctxs(self) -> Any:
        return [{"universe": [{"name": "SOL"}]}, [{"funding": "0.0000125"}]]


class TestCli:
    def test_backtest_from_csv(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from services.analyst.cli import main  # noqa: PLC0415

        path = tmp_path / "sol.csv"
        closes = trend(WARMUP + 200, 100, 0.002) + trend(200, 100 * 1.002 ** (WARMUP + 199), -0.002)
        path.write_text(
            "\n".join(
                f"{int(c.open_time.timestamp() * 1000)},{c.open},{c.high},{c.low},{c.close},1"
                for c in make_candles(closes)
            )
        )
        assert main(["backtest", "--csv", str(path)]) == 0
        out = capsys.readouterr().out
        assert "Full period" in out and "Second half" in out and "buy & hold" in out

    def test_analyze_without_news_proposes_but_refuses_to_execute(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from services.analyst import cli  # noqa: PLC0415

        # Candles that end just before "now", so every one of them is closed.
        candles = make_candles(trend(WARMUP + 10, 100, 0.002))
        shift = datetime.now(UTC) - (candles[-1].open_time + STEP)
        candles = [
            Candle(c.open_time + shift, c.open, c.high, c.low, c.close, c.volume) for c in candles
        ]
        candles = [
            Candle(
                c.open_time.replace(minute=0, second=0, microsecond=0)
                - timedelta(hours=c.open_time.hour % 4),
                c.open,
                c.high,
                c.low,
                c.close,
                c.volume,
            )
            for c in candles
        ]
        monkeypatch.setattr(cli, "_info", lambda *_: FakeInfo(candles))
        assert cli.main(["analyze", "--no-news", "--execute"]) == 1
        captured = capsys.readouterr()
        assert "PROPOSAL  LONG" in captured.out
        assert "news was not checked" in captured.out
        assert "every check must run" in captured.err


def test_simulator_state_survives_a_save_and_reload() -> None:
    """The paper account saves the simulator between candles; nothing may be lost."""
    import json as json_module  # noqa: PLC0415

    from services.analyst.simulator import BacktestConfig as Config  # noqa: PLC0415
    from services.analyst.simulator import Simulator  # noqa: PLC0415

    candles = make_candles(trend(40, 100, 0.002))
    sim = Simulator(Config())
    sim.schedule_entry(Direction.LONG, 90.0, 120.0)
    sim.open_candle(candles[1])
    sim.accrue_funding(0.0001, candles[1].close)
    assert sim.position is not None
    sim.close_at(candles[2].open_time, candles[2].close, "test")
    sim.schedule_entry(Direction.SHORT, 200.0, None)

    restored = Simulator.from_dict(Config(), json_module.loads(json_module.dumps(sim.to_dict())))
    assert restored.to_dict() == sim.to_dict()
    assert restored.cash == sim.cash
    assert restored.trades == sim.trades
    assert restored.pending_entry == (Direction.SHORT, 200.0, None)

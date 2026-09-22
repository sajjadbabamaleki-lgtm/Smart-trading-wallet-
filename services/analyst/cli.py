"""Analyse the chart and news, backtest the strategy, and optionally trade.

    python -m services.analyst.cli analyze  --symbol SOL
    python -m services.analyst.cli analyze  --symbol SOL --execute
    python -m services.analyst.cli backtest --symbol SOL --hyperliquid
    python -m services.analyst.cli backtest --symbol SOL --csv data/SOLUSDT-4h-*.csv

`analyze` uses the exchange and keys in `.env.trader` (see
`services/trader/README.md`) and news classification needs ANTHROPIC_API_KEY.
`--execute` hands the proposal to the trader, which places the entry with its
stop loss and take profit on the exchange; it is refused unless every check
ran. Backtest first: see `services/analyst/README.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs.exchange.errors import OrderOutcomeUnknownError, VenueError  # noqa: E402
from services.analyst.analyst import Analysis, analyse  # noqa: E402
from services.analyst.backtest import (  # noqa: E402
    BacktestConfig,
    BacktestResult,
    Metrics,
    PortfolioResult,
    run_backtest,
    run_portfolio,
)
from services.analyst.candles import (  # noqa: E402
    INTERVALS,
    Candle,
    CandleError,
    fetch_hyperliquid,
    fetch_hyperliquid_funding,
    load_binance_csv,
    validate_series,
)
from services.analyst.news import check_news  # noqa: E402
from services.analyst.strategy import InsufficientHistoryError, StrategyParams  # noqa: E402
from services.trader.config import TraderConfigError, load_trader_settings  # noqa: E402
from services.trader.planner import PlanRejectedError, RiskLimits  # noqa: E402
from services.trader.trader import TradeRefusedError, open_position  # noqa: E402
from services.trader.venues.factory import build_venue  # noqa: E402
from services.trader.venues.hyperliquid import EMPTY_SPOT_META, base_url  # noqa: E402

TOP_10: Final = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT")
"""Fixed before any portfolio result was seen, so the list cannot be picked to
flatter one: ten long-established, liquid assets."""


def _info(mainnet: bool) -> object:
    from hyperliquid.info import Info  # noqa: PLC0415 — network client, created on demand

    return Info(base_url(mainnet), skip_ws=True, spot_meta=EMPTY_SPOT_META, timeout=15)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="analyst", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    analyze = commands.add_parser("analyze", help="analyse now and propose a trade")
    analyze.add_argument("--symbol", default="SOL", type=str.upper)
    analyze.add_argument("--interval", default="4h", choices=sorted(INTERVALS))
    analyze.add_argument("--long-only", action="store_true", help="never propose shorts")
    analyze.add_argument(
        "--no-news", action="store_true", help="skip the news check (blocks --execute)"
    )
    analyze.add_argument("--execute", action="store_true", help="place the proposed trade")
    analyze.add_argument("--yes", action="store_true", help="skip the mainnet confirmation")

    backtest = commands.add_parser("backtest", help="test the strategy on history")
    assets = backtest.add_mutually_exclusive_group()
    assets.add_argument("--symbol", default="SOL", type=str.upper)
    assets.add_argument(
        "--symbols",
        type=lambda text: [s.strip().upper() for s in text.split(",") if s.strip()],
        help="several assets, comma-separated: the same rules on each, capital split equally",
    )
    assets.add_argument(
        "--top10",
        action="store_true",
        help="the fixed list of ten liquid assets: " + ", ".join(TOP_10),
    )
    backtest.add_argument("--interval", default="4h", choices=sorted(INTERVALS))
    source = backtest.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--hyperliquid",
        action="store_true",
        help="Hyperliquid mainnet candles and funding (public data, no key needed)",
    )
    source.add_argument("--csv", nargs="+", type=Path, help="Binance kline CSV files")
    backtest.add_argument("--risk", type=float, default=1.0, help="percent of equity per trade")
    backtest.add_argument("--leverage", type=int, default=3, help="maximum leverage")
    backtest.add_argument("--long-only", action="store_true", help="never take shorts")
    return parser


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


def _print_analysis(analysis: Analysis) -> None:
    signal = analysis.signal
    closed = f"{analysis.as_of:%Y-%m-%d %H:%M}"
    print(f"{analysis.symbol} {analysis.interval} — last closed candle {closed} UTC")
    print(f"  price           {signal.close:.6g}")
    print(f"  trend score     {signal.score:+.2f}  (-1 strong downtrend … +1 strong uptrend)")
    for name, vote in signal.votes.items():
        print(f"    {name:<16} {'up' if vote > 0 else 'down' if vote < 0 else 'flat'}")
    print(f"  ATR(14)         {signal.atr:.4g}")
    if analysis.funding_hourly is not None:
        print(f"  funding         {analysis.funding_hourly * 24 * 365:+.1%} a year")
    upcoming = analysis.calendar.next_event
    if upcoming is not None:
        print(f"  next macro      {upcoming.name} {upcoming.at:%Y-%m-%d %H:%M %Z}")
    if analysis.news is not None:
        print(f"  news            {analysis.news.headlines_considered} headlines, last 24h")
        for note in analysis.news.notes:
            print(f"    note: {note}")
    for reason in signal.reasons:
        print(f"  • {reason}")
    for veto in analysis.vetoes:
        print(f"  ✗ {veto}")
    if analysis.direction is not None and signal.stop_loss and signal.take_profit:
        print(
            f"\nPROPOSAL  {analysis.direction.value.upper()}  "
            f"stop {signal.stop_loss:.6g}  target {signal.take_profit:.6g}"
        )
    else:
        print("\nNO TRADE")
    for blocker in analysis.automation_blockers:
        print(f"  automatic execution blocked: {blocker}")


async def _execute(analysis: Analysis, args: argparse.Namespace) -> int:
    settings = load_trader_settings()
    venue, uses_api_key = build_venue(settings, needs_signer=True)
    try:
        if not uses_api_key:
            print("WARNING: the configured key is the main wallet's own key.", file=sys.stderr)
        if venue.is_mainnet and not args.yes:
            answer = input(f"{venue.name} MAINNET: this uses real money. Type 'yes' to send: ")
            if answer.strip().lower() != "yes":
                raise TradeRefusedError("not confirmed")
        direction = analysis.direction
        signal = analysis.signal
        assert direction is not None and signal.stop_loss is not None  # noqa: S101 — checked by caller
        result = await open_position(
            venue,
            symbol=analysis.symbol,
            direction=direction,
            stop_loss=Decimal(str(signal.stop_loss)),
            take_profit=Decimal(str(signal.take_profit)) if signal.take_profit else None,
            limits=RiskLimits(
                risk_percent=settings.default_risk_percent,
                max_leverage=settings.max_leverage,
                taker_fee_rate=settings.taker_fee_rate,
                slippage_percent=settings.slippage_percent,
            ),
            execute=True,
        )
        plan = result.plan
        print(
            f"\nSENT  {plan.symbol} {plan.direction.value.upper()} {plan.amount} "
            f"(${plan.notional:.2f}), stop {plan.stop_loss}, target {plan.take_profit}, "
            f"risk ${plan.loss_at_stop:.2f}"
        )
        if not result.stop_confirmed:
            print("WARNING: the stop loss could not be confirmed on the exchange. Check now.")
        return 0
    finally:
        await venue.aclose()


def _analyze(args: argparse.Namespace) -> int:
    settings = load_trader_settings()
    now = datetime.now(UTC)
    news_checker = None if args.no_news else (lambda s, d, t: check_news(s, d, now=t))
    analysis = analyse(
        _info(settings.is_mainnet),
        symbol=args.symbol,
        interval=args.interval,
        now=now,
        news_checker=news_checker,
        params=StrategyParams(allow_short=not args.long_only),
    )
    _print_analysis(analysis)
    if not args.execute:
        return 0
    if analysis.direction is None:
        print("nothing to execute")
        return 0
    if not analysis.may_auto_execute:
        print("refused: every check must run before a trade is placed", file=sys.stderr)
        return 1
    return asyncio.run(_execute(analysis, args))


# ---------------------------------------------------------------------------
# backtest
# ---------------------------------------------------------------------------


def _fmt_pf(value: float) -> str:
    return "∞" if math.isinf(value) else f"{value:.2f}"


def _print_metrics(title: str, m: Metrics) -> None:
    print(f"\n{title}: {m.start:%Y-%m-%d} → {m.end:%Y-%m-%d}")
    print(
        f"  trades            {m.trades}   win rate {m.win_rate:.0%}   average {m.average_r:+.2f}R"
    )
    print(f"  profit factor     {_fmt_pf(m.profit_factor)}")
    print(f"  return            {m.total_return:+.1%}   CAGR {m.cagr:+.1%}")
    print(f"  max drawdown      {m.max_drawdown:.1%}")
    print(f"  Sharpe            {m.sharpe:.2f}   P(true Sharpe > 0) {m.probabilistic_sharpe:.0%}")
    print(f"  time in market    {m.exposure:.0%}")
    print(f"  costs             fees ${m.fees:,.2f}   funding ${m.funding:,.2f}")
    print(
        f"  buy & hold        {m.buy_and_hold_return:+.1%}   "
        f"max drawdown {m.buy_and_hold_max_drawdown:.1%}"
    )


def _print_backtest(result: BacktestResult) -> None:
    _print_metrics("Full period", result.full)
    _print_metrics("First half", result.first_half)
    _print_metrics("Second half", result.second_half)
    for name, stats in (("Longs", result.longs), ("Shorts", result.shorts)):
        print(
            f"\n{name}: {stats.trades} trades, win rate {stats.win_rate:.0%}, "
            f"average {stats.average_r:+.2f}R, profit factor {_fmt_pf(stats.profit_factor)}, "
            f"net ${stats.net_pnl:,.2f}"
        )
    if result.skipped_signals:
        print(
            f"\n{result.skipped_signals} signals skipped (below minimum size or gapped past stop)"
        )
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    print(
        "\nRead this as evidence, not a promise: parameters were fixed before testing, and a"
        "\nresult that holds in both halves and beats buy & hold on drawdown is the minimum"
        "\nbar before paper trading — not before real money."
    )


def _print_portfolio(result: PortfolioResult) -> None:
    print("\nPer asset (same rules, equal share of capital):")
    print(f"  {'asset':<6} {'trades':>6} {'win':>5} {'avg R':>7} {'return':>8} {'P(SR>0)':>8}")
    for symbol, r in result.per_asset.items():
        m = r.full
        print(
            f"  {symbol:<6} {m.trades:>6} {m.win_rate:>5.0%} {m.average_r:>+7.2f} "
            f"{m.total_return:>+8.1%} {m.probabilistic_sharpe:>8.0%}"
        )
    profitable = sum(1 for r in result.per_asset.values() if r.full.total_return > 0)
    print(f"  profitable on {profitable} of {len(result.per_asset)} assets")
    print(f"\nTrades per week: {result.trades_per_week:.1f}")
    _print_metrics("Portfolio, full period", result.full)
    _print_metrics("Portfolio, first half", result.first_half)
    _print_metrics("Portfolio, second half", result.second_half)
    for name, stats in (("Longs", result.longs), ("Shorts", result.shorts)):
        print(
            f"\n{name}: {stats.trades} trades, win rate {stats.win_rate:.0%}, "
            f"average {stats.average_r:+.2f}R, profit factor {_fmt_pf(stats.profit_factor)}, "
            f"net ${stats.net_pnl:,.2f}"
        )
    print("\n(buy & hold here is an equal-weight basket of the same assets)")
    for warning in result.warnings:
        print(f"WARNING: {warning}")


def _backtest(args: argparse.Namespace) -> int:
    config = BacktestConfig(
        interval=args.interval,
        risk_percent=args.risk,
        max_leverage=args.leverage,
        params=StrategyParams(allow_short=not args.long_only),
    )
    symbols = list(TOP_10) if args.top10 else args.symbols
    if symbols:
        if not args.hyperliquid:
            raise ValueError("several assets are backtested from Hyperliquid; add --hyperliquid")
        info = _info(mainnet=True)
        now = datetime.now(UTC)
        candles_by_symbol: dict[str, Sequence[Candle]] = {}
        funding_by_symbol: dict[str, dict[datetime, float]] = {}
        for symbol in symbols:
            try:
                candles = fetch_hyperliquid(info, symbol, args.interval, now=now)
                funding = fetch_hyperliquid_funding(
                    info, symbol, start=candles[0].open_time, end=now
                )
            except Exception as exc:  # noqa: BLE001 — one missing asset must not stop the rest
                print(f"{symbol}: skipped ({type(exc).__name__}: {exc})")
                continue
            candles_by_symbol[symbol] = candles
            funding_by_symbol[symbol] = funding
            print(f"{symbol}: {len(candles)} candles, {len(funding)} funding rates")
        _print_portfolio(
            run_portfolio(candles_by_symbol, config, funding_by_symbol=funding_by_symbol)
        )
        return 0

    history: dict[datetime, float] | None = None
    if args.hyperliquid:
        info = _info(mainnet=True)
        now = datetime.now(UTC)
        candles = fetch_hyperliquid(info, args.symbol, args.interval, now=now)
        history = fetch_hyperliquid_funding(info, args.symbol, start=candles[0].open_time, end=now)
        print(f"{len(candles)} Hyperliquid candles, {len(history)} hourly funding rates")
    else:
        candles = validate_series(load_binance_csv(args.csv), args.interval)
        print(f"{len(candles)} candles from {len(args.csv)} file(s) — Binance spot, not the perp")
    _print_backtest(run_backtest(candles, config, funding_rates=history))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _analyze(args) if args.command == "analyze" else _backtest(args)
    except OrderOutcomeUnknownError as exc:
        print(f"UNKNOWN: {exc}", file=sys.stderr)
        return 3
    except TraderConfigError as exc:
        print(f"configuration: {exc}", file=sys.stderr)
        return 2
    except (
        CandleError,
        InsufficientHistoryError,
        PlanRejectedError,
        TradeRefusedError,
        VenueError,
        ValueError,
    ) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

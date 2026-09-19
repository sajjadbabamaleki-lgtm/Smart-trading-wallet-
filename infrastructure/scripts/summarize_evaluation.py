"""Compress a strategy evaluation into one line per run.

`make evaluate-report` produces a few hundred lines across sixteen runs and
writes them into the repository, which was meant to be how the result travels.
It does not travel: the recording host can pull from GitHub but has no
credential to push, so the file stays on the VPS.

One line per run fits in a message. That is all this does — it reads the file
that already exists rather than asking for the evaluation to be run again, and
it prints the six numbers a decision actually turns on: how often the rule
traded, what it returned, what it gave back on the way, what each trade earned
against what each trade cost, and how many shuffled orderings of its own
decisions did as well.

Parsing rendered text is normally the wrong way round, and it is the right way
round here: the alternative is re-running sixteen backtests to obtain numbers
that are already sitting in a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

EVALUATIONS = Path("docs/evidence/build-0.1/evaluations")

HEADER = re.compile(
    # The trailing fields are optional and unanchored to a fixed set, because
    # this line has already grown once (it gained the venue) and the parser
    # must survive it growing again rather than silently matching nothing.
    r"^(?P<asset>[A-Z]{2,10}) (?P<interval>\S+), rule: (?P<rule>[^,\s]+)"
    r"(?:, venue: (?P<venue>[^,\s]+))?.*$"
)
PERIOD = re.compile(
    # "TRAINING, THIRD OF 4" and the like, as well as the original halves. The
    # ordinal is captured so a split into any number of parts is labelled
    # rather than silently collapsing into TRAIN — which would put two periods
    # under one name, the defect this parser already had once.
    r"^(?P<label>TRAINING PERIOD|HOLDOUT PERIOD|"
    r"TRAINING, (?P<ordinal>[A-Z]+|PART \d+) (?:HALF|OF \d+)): "
)
ROW = re.compile(
    r"^  (?P<name>\S+)\s+(?P<trades>\d+)\s+(?P<win>[\d.]+%|-)\s+"
    r"(?P<ret>-?[\d.]+)%\s+(?P<dd>[\d.]+)%\s+(?P<expo>\d+)%\s*$"
)
ECONOMICS = re.compile(
    r"^  (?P<name>\S+)\s+gross\s+(?P<gross>[+-][\d.]+) bps/trade\s+"
    r"cost\s+(?P<cost>[\d.]+)\s+net\s+(?P<net>[+-][\d.]+)"
)
SHUFFLE = re.compile(r"^  vs shuffled : (?P<beaten>\d+) of (?P<total>\d+)")
HOLD = re.compile(r"^  vs buy-hold : (?P<points>[+-][\d.]+) points")
VERDICT = re.compile(r"^  VERDICT: (?P<verdict>.+?)\.?\s*$")


RULE_WIDTH = 28
"""Wide enough for the longest rule name a wrapper produces.

A truncated name in a summary is a name somebody has to go and look up, and
`trend-following-confirmed-3` is as long as these get.
"""


def _short(verdict: str) -> str:
    """The verdict's first clause, which is the part that differs between runs.

    The explanations are worth reading once and they repeat verbatim sixteen
    times. The full text stays in the evaluation file.
    """
    if verdict.startswith("NO_EDGE_FOUND"):
        reason = verdict.split("—", 1)
        return "NO_EDGE: " + (reason[1].strip() if len(reason) > 1 else "")
    if verdict.startswith("candidate survived"):
        return "SURVIVED"
    return verdict


@dataclass
class Run:
    asset: str
    interval: str
    rule: str
    venue: str = "hyperliquid"
    period: str = "TRAIN"
    trades: str = "-"
    win: str = "-"
    ret: str = "-"
    drawdown: str = "-"
    exposure: str = "-"
    gross: str = "-"
    cost: str = "-"
    beaten: str = "-"
    versus_hold: str = "-"
    verdict: str = "-"

    def line(self) -> str:
        return (
            f"{self.venue[:4]:<4} {self.asset:<4} {self.interval:<3} "
            f"{self.rule[:RULE_WIDTH]:<{RULE_WIDTH}} "
            f"{self.period:<5} {self.trades:>5} {self.win:>6} {self.ret:>6} "
            f"{self.drawdown:>6} {self.exposure:>5} {self.gross:>7} {self.cost:>6} "
            f"{self.beaten:>6} {self.versus_hold:>6}  {_short(self.verdict)}"
        )


def parse(text: str) -> list[Run]:
    """Read the runs out of a rendered evaluation.

    **One row per period, not per invocation.** A single CLI run prints the
    asset/interval/rule header once and then evaluates several periods under
    it — the full training period and, with --halves, each half. The first
    version of this keyed a row on the header, so three periods collapsed into
    one row: the guarded columns kept the first period's numbers while the
    unguarded ones were overwritten by the last, and the row that came out was
    two different periods wearing one label. A summary that mixes periods is
    worse than no summary, because it reads like a result.

    So the header only sets the context, and a period line starts the row.

    Deliberately forgiving otherwise. An unrecognised line is skipped rather
    than raised on, because a partial summary of a real file is useful and a
    crash on an unexpected line is not.
    """
    runs: list[Run] = []
    context: tuple[str, str, str, str] | None = None
    current: Run | None = None
    for line in text.splitlines():
        header = HEADER.match(line)
        if header:
            context = (
                header["asset"],
                header["interval"],
                header["rule"],
                header["venue"] or "hyperliquid",
            )
            current = None
            continue

        period = PERIOD.match(line)
        if period:
            if context is None:
                continue
            asset, interval, rule, venue = context
            current = Run(
                asset=asset,
                interval=interval,
                rule=rule,
                venue=venue,
                period=_period_label(period["label"]),
            )
            runs.append(current)
            continue

        if current is None:
            continue

        # The candidate is identified by not being a control, never by the
        # requested rule name: a wrapped rule renames itself, so
        # `--rule trend-confirmed` prints as `trend-following-confirmed-2`.
        row = ROW.match(line)
        if row and not row["name"].startswith("control-") and current.trades == "-":
            current.trades = row["trades"]
            current.win = row["win"]
            current.ret = f"{row['ret']}%"
            current.drawdown = f"{row['dd']}%"
            current.exposure = f"{row['expo']}%"
            current.rule = row["name"]
            continue
        economics = ECONOMICS.match(line)
        if economics and not economics["name"].startswith("control-") and current.gross == "-":
            current.gross = economics["gross"]
            current.cost = economics["cost"]
            continue
        shuffle = SHUFFLE.match(line)
        if shuffle and current.beaten == "-":
            current.beaten = f"{shuffle['beaten']}/{shuffle['total']}"
            continue
        hold = HOLD.match(line)
        if hold and current.versus_hold == "-":
            current.versus_hold = hold["points"]
            continue
        verdict = VERDICT.match(line)
        if verdict and current.verdict == "-":
            current.verdict = verdict["verdict"]
    return runs


SHORT_ORDINALS: Final = {
    "FIRST": "1st",
    "SECOND": "2nd",
    "THIRD": "3rd",
    "FOURTH": "4th",
    "FIFTH": "5th",
    "SIXTH": "6th",
}


def _period_label(raw: str) -> str:
    """Short labels, so a row fits a line and the periods cannot be confused.

    An unrecognised part number falls through to the raw ordinal rather than
    to TRAIN. A label that quietly becomes TRAIN would put a sub-period's
    numbers under the full period's name, which is how this parser previously
    reported two periods as one.
    """
    if raw.startswith("HOLDOUT"):
        return "HOLD"
    if not raw.startswith("TRAINING, "):
        return "TRAIN"
    ordinal = raw.removeprefix("TRAINING, ").split(" ", 1)[0]
    return SHORT_ORDINALS.get(ordinal, ordinal.lower()[:4])


def newest() -> Path:
    """The most recent evaluation, since that is the one just produced."""
    candidates = sorted(EVALUATIONS.glob("*/evaluation.txt"))
    if not candidates:
        raise SystemExit(
            f"no evaluation found under {EVALUATIONS}. Run `make evaluate-report` first."
        )
    return candidates[-1]


def main() -> int:
    import argparse  # noqa: PLC0415 - CLI-local

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="an evaluation.txt; the newest by default")
    args = parser.parse_args()

    path = Path(args.path) if args.path else newest()
    runs = parse(path.read_text())
    if not runs:
        raise SystemExit(f"{path} contains no recognisable runs")

    print(f"# {path}")
    print(f"# {len(runs)} runs")
    print()
    print(
        f"{'src':<4} {'asset':<4} {'int':<3} {'rule':<{RULE_WIDTH}} {'per':<5} {'trds':>5} "
        f"{'win':>6} {'ret':>6} {'dd':>6} {'expo':>5} {'gross':>7} {'cost':>6} "
        f"{'shuf':>6} {'vsBH':>6}  verdict"
    )
    for run in runs:
        print(run.line())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

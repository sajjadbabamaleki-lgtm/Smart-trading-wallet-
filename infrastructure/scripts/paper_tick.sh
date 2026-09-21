#!/usr/bin/env bash
# One turn of the loop: refresh history, decide on every book, publish the result.
#
# This is what the timer runs. It is the first thing in the project that goes
# from data to decision to written record without anyone typing a command, and
# the order matters: history first, because a decision on stale candles is
# worse than no decision; then each book; then the report, pushed to the
# repository so the outcome can be read without copying a terminal.
#
# It does not stop on a single failure. A venue that refuses one asset must not
# prevent the other three from being decided, and a download that fails must
# not stop the books that already have fresh data. Every failure is counted and
# named in the output, and the exit status reports whether any occurred — so a
# partial run is visible rather than silent.
#
# No capital, no venue, no order. Every position it takes is a row in a table.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

# Git must never wait for a human. Under systemd there is nobody to answer,
# so a credential prompt does not fail — it hangs until TimeoutStartSec kills
# the unit twenty minutes later, having written nothing and explained nothing.
# A tick that dies silently is indistinguishable from a timer that never
# fired, which is two hours of guessing every time it happens.
#
# Set once for the whole script rather than on the push alone: the fetch and
# the rebase added later reach the network too, and the version of this that
# only covered `git push` left exactly that gap.
export GIT_TERMINAL_PROMPT=0
export GIT_ASKPASS=/bin/true

UV="${UV:-uv}"
ASSETS="${ASSETS:-BTC ETH SOL BNB}"
INTERVAL="${INTERVAL:-4h}"
VENUE="${VENUE:-binance}"
RULE="${RULE:-funding-extreme}"
PUSH="${PUSH:-1}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="docs/evidence/build-0.1/paper/report.txt"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
failures=0

# Preflight, before anything that could be blamed on a venue. The loop died
# for eleven hours because systemd ran it without /root/.local/bin on PATH:
# every `uv run` failed identically, and the tick reported thirteen separate
# failures — "history refresh failed for BTC", "tick did not record for ETH" —
# each of which points at a download or a venue, and none of which points at
# the missing binary that caused all of them.
#
# One check, one message with the actual cause, and an exit before the noise.
# A tick that cannot run uv has not partially failed; it has not started.
if ! command -v "$UV" >/dev/null 2>&1; then
  echo "cannot run: '${UV}' is not on PATH"
  echo "  PATH=${PATH}"
  echo "  uv installs to ~/.local/bin; under systemd the unit must set"
  echo "  Environment=PATH=... because systemd does not read a login shell."
  exit 1
fi

echo "=== paper tick ${STAMP} — ${RULE} on ${INTERVAL} (${VENUE}) ==="

# History first. Only the recent window: the archive is already stored, and a
# tick that re-downloaded nine years would take longer than the interval it
# runs on.
for asset in $ASSETS; do
  if ! "$UV" run python -m services.research.history_cli \
      --asset "$asset" --interval "$INTERVAL" --days 30 --source "$VENUE" >/dev/null 2>&1; then
    echo "  history refresh failed for $asset"
    failures=$((failures + 1))
  fi
  if ! "$UV" run python -m services.research.funding_cli \
      --asset "$asset" --days 30 >/dev/null 2>&1; then
    echo "  funding refresh failed for $asset"
    failures=$((failures + 1))
  fi
done

# Outside information, once per tick rather than once per asset: the sentiment
# index is one series for the whole market and the feeds are not per-asset
# either. A failure here does not stop the decisions — a rule that needs a
# series it does not have refuses on its own, which is the behaviour wanted.
if ! "$UV" run python -m services.research.information_cli >/dev/null 2>&1; then
  echo "  information refresh failed (sentiment and headlines)"
  failures=$((failures + 1))
fi

for asset in $ASSETS; do
  echo
  if ! "$UV" run python -m services.strategy_engine.paper_cli \
      --asset "$asset" --interval "$INTERVAL" --venue "$VENUE" --rule "$RULE"; then
    # Exit 2 is a refusal on stale data, which is the engine working. It is
    # still counted, because a refusal every tick means the download is broken.
    echo "  tick did not record for $asset"
    failures=$((failures + 1))
  fi
done

echo
mkdir -p "$(dirname "$REPORT")"
if ! "$UV" run python -m services.strategy_engine.paper_report_cli > "$REPORT" 2>&1; then
  echo "  report failed"
  failures=$((failures + 1))
fi
cat "$REPORT"

echo
echo "failures this tick: ${failures}"

if [ "$PUSH" != "1" ]; then
  echo "PUSH=0 — report written to $REPORT, not pushed"
  exit $(( failures > 0 ))
fi

# A single file, always at the same path, so the history of the loop is the
# file's git history rather than a directory that grows a report per tick.
git add "$REPORT"
if git diff --cached --quiet; then
  echo "report written unchanged"
else
  git \
    -c user.name="${GIT_AUTHOR_NAME:-paper trader}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-paper@localhost}" \
    commit -q -m "Paper trading report ${STAMP}" -- "$REPORT"
fi

# Catching up on what earlier ticks could not send, not just this one. The
# loop committed four reports it never pushed before anyone noticed, because
# the old code only pushed when *this* tick changed the report — so once a
# push started failing, every later tick with an unchanged report said
# "nothing to push" and the backlog stayed invisible.
waiting="$(git rev-list --count "origin/${BRANCH}..HEAD" 2>/dev/null || echo 0)"
if [ "${waiting:-0}" -eq 0 ]; then
  echo "nothing to push"
  exit $(( failures > 0 ))
fi

# The branch is shared with whoever is working on the code, so the remote
# moves under the loop. CLAUDE.md warns a person to "fetch and rebase" for
# exactly this reason; nobody told the loop. A single push of my own was
# enough to make every subsequent tick fail to report, permanently, until a
# human ran git by hand — which is the worst shape a failure can have here,
# because the report is the only thing that reaches the far end.
#
# Rebase rather than merge: the report is one file whose newest version
# supersedes the last, so a linear history of it is the record, and merge
# commits would bury it.
sync_onto_remote() {
  git fetch -q origin "$BRANCH" 2>/dev/null || return 1
  git rev-parse --verify -q "origin/${BRANCH}" >/dev/null || return 1
  # `-X theirs` during a rebase favours the commits being replayed — ours.
  # That is the right resolution and its blast radius is one file: the tick
  # only ever commits $REPORT, so a conflict can only be in $REPORT, and the
  # newer report is always the one to keep.
  # The same identity the commit above supplies inline, and for the same
  # reason: a rebase writes commits too, and it refuses without a committer.
  # Relying on the host's global git config would make the loop work on the
  # machine it was written on and fail on the one it runs on.
  if ! git \
      -c core.editor=true \
      -c user.name="${GIT_AUTHOR_NAME:-paper trader}" \
      -c user.email="${GIT_AUTHOR_EMAIL:-paper@localhost}" \
      rebase -q -X theirs "origin/${BRANCH}" >/dev/null 2>&1; then
    # Never leave the repository mid-rebase. The next tick would fail on a
    # state no one asked for, and the owner would be debugging git rather
    # than reading a report.
    git rebase --abort >/dev/null 2>&1 || true
    return 1
  fi
}

push_now() { git push -q origin "$BRANCH" 2>/dev/null; }

if sync_onto_remote && push_now; then
  echo "pushed ${waiting} report(s) to origin/$BRANCH"
# One retry, for the race the first attempt cannot avoid: something pushed
# between our fetch and our push. Retrying without re-syncing would fail the
# same way, and retrying forever would hold the unit open against a venue
# outage, so it is exactly one.
elif sync_onto_remote && push_now; then
  echo "pushed ${waiting} report(s) to origin/$BRANCH on the second attempt"
else
  echo "  push failed; ${waiting} report(s) committed locally, newest at $REPORT"
  echo "  the decisions are recorded — only the reporting of them is stuck"
  failures=$((failures + 1))
fi

exit $(( failures > 0 ))

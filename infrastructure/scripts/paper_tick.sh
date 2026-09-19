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
  echo "report unchanged; nothing to push"
else
  git \
    -c user.name="${GIT_AUTHOR_NAME:-paper trader}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-paper@localhost}" \
    commit -q -m "Paper trading report ${STAMP}" -- "$REPORT"
  if GIT_TERMINAL_PROMPT=0 git push -q origin "$BRANCH"; then
    echo "pushed to origin/$BRANCH"
  else
    echo "push failed; the report is committed locally at $REPORT"
    failures=$((failures + 1))
  fi
fi

exit $(( failures > 0 ))

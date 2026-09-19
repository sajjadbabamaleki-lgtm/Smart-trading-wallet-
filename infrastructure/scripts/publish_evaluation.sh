#!/usr/bin/env bash
# Put a full strategy evaluation somewhere it can be read from.
#
# The same reasoning as publish_recording_report.sh, and the same problem it
# solved. An evaluation prints several hundred lines across two assets, two
# intervals and four rules. Read off a phone screenshot it arrives in pieces,
# the interesting rows are the ones that scrolled past, and a decision gets
# made on the part that happened to be visible. The repository is the channel
# the host and everyone else already share, so the whole thing goes there.
#
#   make evaluate-report                 # the full matrix, training period
#   make evaluate-report HOLDOUT=1       # also spend the held-out period
#   make evaluate-report PUSH=0          # write and commit, do not push
#
# Nothing here reads or writes a credential. The output is returns, trade
# counts and timestamps.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

UV="${UV:-uv}"
INTERVALS="${INTERVALS:-4h 1d}"
ASSETS="${ASSETS:-BTC SOL}"
RULES="${RULES:-trend-following trend-confirmed trend-confirmed-3 trend-following-calm}"
SHUFFLES="${SHUFFLES:-20}"
PUSH="${PUSH:-1}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DIR="docs/evidence/build-0.1/evaluations/${STAMP}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

HOLDOUT_FLAG=""
if [ "${HOLDOUT:-0}" = "1" ]; then
  HOLDOUT_FLAG="--holdout"
fi

WORK="$(mktemp -d)"
# Written to a temporary directory first: a run that cannot reach ClickHouse
# should fail with the store's own error and leave nothing behind, because an
# empty evaluation file reads exactly like a strategy that found nothing.
trap 'rm -rf "$WORK"' EXIT
OUT="$WORK/evaluation.txt"

{
  echo "Strategy evaluation ${STAMP}"
  echo "shuffles per rule: ${SHUFFLES}"
  if [ -n "$HOLDOUT_FLAG" ]; then
    echo "HOLDOUT SPENT: the reserved period was evaluated in this run"
  else
    echo "holdout: reserved, not evaluated"
  fi
  echo "commit: $(git rev-parse --short HEAD)"
  echo
} > "$OUT"

for asset in $ASSETS; do
  for interval in $INTERVALS; do
    for rule in $RULES; do
      echo "=======================================================" >> "$OUT"
      "$UV" run python -m services.strategy_engine.evaluate_candles_cli \
        --asset "$asset" --interval "$interval" --rule "$rule" \
        --shuffles "$SHUFFLES" $HOLDOUT_FLAG >> "$OUT" 2>&1
      echo >> "$OUT"
    done
  done
done

mkdir -p "$DIR"
mv "$OUT" "$DIR/"

echo "----- $DIR/evaluation.txt -----"
# The whole file is long by design. Printed tail-first so a terminal shows the
# most recent runs; the file is the record.
wc -l "$DIR/evaluation.txt"
grep -E "^(BTC|SOL|  VERDICT|  vs )" "$DIR/evaluation.txt" || true
echo "---------------------------------------------"
echo

git add "$DIR/evaluation.txt"

if git diff --cached --quiet; then
  echo "nothing new to commit — the evaluation is at $DIR"
else
  git \
    -c user.name="${GIT_AUTHOR_NAME:-recording host}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-recorder@localhost}" \
    commit -q -m "Strategy evaluation ${STAMP}" -- "$DIR"
  echo "committed $DIR on $BRANCH"
fi

if [ "$PUSH" != "1" ]; then
  echo "PUSH=0 — not pushing. Send it with: git push origin $BRANCH"
  exit 0
fi

# Never prompt: a host with no credential helper otherwise waits forever on
# "Username for 'https://github.com':" while looking like it is still working.
if GIT_TERMINAL_PROMPT=0 git push origin "$BRANCH"; then
  echo
  echo "pushed to origin/$BRANCH — the evaluation is readable from the repository now."
else
  echo
  echo "push failed (most likely this host has no credential for GitHub)."
  echo "The evaluation is committed locally at $DIR — nothing was lost."
  echo "  cat $DIR/evaluation.txt"
  exit 1
fi

#!/usr/bin/env bash
# Put what the store holds somewhere it can be read from.
#
# `make inspect` prints a report to the terminal of whoever ran it. That is the
# wrong place for it: the recording host is a VPS, the people reasoning about
# the recording are not on it, and a report that has to be copied out of an SSH
# session by hand arrives partially or not at all. This writes the same report
# to the repository and pushes it, because the repository is the one channel
# the host and everyone else already share.
#
# Both forms are kept. The text is what a person reads; the JSON is what a
# later script reads, and re-deriving it from rendered text is not possible.
#
#   make report              # last 24 hours
#   make report HOURS=6      # just the run that finished
#   make report PUSH=0       # write and commit, leave pushing to you
#
# Nothing here reads a credential or writes one out. The report contains row
# counts, timestamps and gap rows - no settings, no DSN, no key.
set -euo pipefail

HOURS="${HOURS:-24}"
PUSH="${PUSH:-1}"

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

UV="${UV:-uv}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DIR="docs/evidence/build-0.1/recordings/${STAMP}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

WORK="$(mktemp -d)"
# Generated into a temporary directory first. A run that cannot reach
# ClickHouse should fail with the store's own error and leave nothing behind -
# an empty report.txt in the repository reads exactly like a recording that
# captured nothing, which is the one thing it must never be mistaken for.
trap 'rm -rf "$WORK"' EXIT

"$UV" run python infrastructure/scripts/inspect_recording.py --hours "$HOURS" > "$WORK/report.txt"
"$UV" run python infrastructure/scripts/inspect_recording.py --hours "$HOURS" --json > "$WORK/report.json"

mkdir -p "$DIR"
mv "$WORK/report.txt" "$WORK/report.json" "$DIR/"

echo "----- $DIR/report.txt -----"
cat "$DIR/report.txt"
echo "---------------------------------------------"
echo

# Only these two paths are staged, and the commit below names them again, so
# whatever else is dirty on the recording host stays dirty rather than being
# swept into a commit nobody meant to make.
git add "$DIR/report.txt" "$DIR/report.json"

if git diff --cached --quiet; then
  echo "nothing new to commit — the report is at $DIR"
else
  git \
    -c user.name="${GIT_AUTHOR_NAME:-recording host}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-recorder@localhost}" \
    commit -q -m "Recording report ${STAMP} (last ${HOURS}h)" -- "$DIR"
  echo "committed $DIR on $BRANCH"
fi

if [ "$PUSH" != "1" ]; then
  echo "PUSH=0 — not pushing. Send it with: git push origin $BRANCH"
  exit 0
fi

# Never prompt. A host without a credential helper otherwise stops on
# "Username for 'https://github.com':" and waits forever - which is worse than
# failing, because the run looks like it is still working and the report it
# already wrote goes unmentioned.
if GIT_TERMINAL_PROMPT=0 git push origin "$BRANCH"; then
  echo
  echo "pushed to origin/$BRANCH — the report is readable from the repository now."
else
  # A host that can pull over HTTPS without a token cannot push, and that is a
  # normal way for this to end. Saying so beats a stack trace, and the report
  # is already committed either way.
  echo
  echo "push failed (most likely this host has no credential for GitHub)."
  echo "The report is committed locally at $DIR — nothing was lost."
  echo "Either give this host push access, or copy the file out:"
  echo "  cat $DIR/report.txt"
  exit 1
fi

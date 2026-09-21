#!/usr/bin/env bash
# Why is the loop not reporting? Six lines, plain words, no journal to read.
#
# `make paper-status` prints forty lines of journalctl. The owner works from a
# phone and has been asked twice to screenshot output that a program could
# have summarised — CLAUDE.md forbids exactly that, and this is the summariser
# it asks for.
#
# Deliberately bash and deliberately dependency-free: the two failures this
# exists to diagnose are `uv` missing from PATH and the timer never firing, and
# a diagnostic written in `uv run python` would be the first casualty of the
# first one.
#
# Every external command goes through a named function so the tests can put a
# fake systemctl and a fake git on PATH and exercise each verdict.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

REPORT="docs/evidence/build-0.1/paper/report.txt"
problems=0

note() { printf '  %s\n' "$1"; }
bad() { printf '  %s\n' "$1"; problems=$((problems + 1)); }

echo "=== paper loop ==="

# 1. Is the timer armed at all?
state="$(systemctl is-active stw-paper.timer 2>/dev/null || true)"
if [ "$state" = "active" ]; then
  note "timer        armed"
else
  bad "timer        NOT armed (${state:-unknown}) — run: make paper-install"
fi

# 2. When next, in UTC. The timer's whole bug was that its schedule was read
# in local time, so a local-time answer here would hide a repeat of it.
next="$(systemctl show stw-paper.timer -p NextElapseUSecRealtime --value 2>/dev/null || true)"
if [ -n "$next" ] && [ "$next" != "0" ] && [ "$next" != "n/a" ]; then
  note "next run     $(date -u -d "$next" '+%Y-%m-%d %H:%M UTC' 2>/dev/null || echo "$next")"
  hour="$(date -u -d "$next" '+%H' 2>/dev/null || echo "")"
  case "$hour" in
    00 | 04 | 08 | 12 | 16 | 20) ;;
    "") ;;
    *) bad "             ^ not a 4h candle close — the timer file is the old one" ;;
  esac
else
  note "next run     unknown"
fi

# 3. Did the last run succeed? A oneshot that failed leaves its status here,
# which is the same thing journalctl would say and forty lines shorter.
result="$(systemctl show stw-paper.service -p Result --value 2>/dev/null || true)"
last="$(systemctl show stw-paper.service -p ExecMainExitTimestamp --value 2>/dev/null || true)"
if [ -n "$last" ] && [ "$last" != "n/a" ]; then
  note "last run     $(date -u -d "$last" '+%Y-%m-%d %H:%M UTC' 2>/dev/null || echo "$last") — ${result:-unknown}"
else
  note "last run     never since boot"
fi

# 4. Can the tick actually run? This is the outage of 2026-09-20, asked
# directly. The service's own PATH is what matters, not this shell's.
unit_path="$(systemctl show stw-paper.service -p Environment --value 2>/dev/null | tr ' ' '\n' | grep '^PATH=' || true)"
if [ -z "$unit_path" ]; then
  bad "uv           service sets no PATH — every uv call will fail"
elif ! PATH="${unit_path#PATH=}" command -v uv >/dev/null 2>&1; then
  bad "uv           not found on the service's own PATH"
else
  note "uv           found on the service's PATH"
fi

# 5. Did a tick write a report it could not push? The report is the only thing
# that reaches the repository, so a commit stuck here is an invisible tick.
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")"
unpushed="$(git log --oneline "origin/${branch}..HEAD" 2>/dev/null | wc -l | tr -d ' ')"
if [ "${unpushed:-0}" -gt 0 ]; then
  bad "push         ${unpushed} commit(s) written but never pushed — the loop ran and could not report"
else
  note "push         nothing waiting"
fi

# 6. How old is the record itself, which is the number that actually matters.
if [ -f "$REPORT" ]; then
  age=$(( ( $(date -u +%s) - $(date -u -r "$REPORT" +%s) ) / 60 ))
  note "report       ${age} min old"
  if grep -q "command not found" "$REPORT" 2>/dev/null; then
    bad "             ^ the report holds an error, not a record"
  fi
else
  bad "report       missing at $REPORT"
fi

echo
if [ "$problems" -eq 0 ]; then
  echo "nothing wrong that this can see."
else
  echo "${problems} problem(s) above."
fi
exit $(( problems > 0 ))

# Working on this repository

Read this first. It is short on purpose; `docs/HANDOVER.md` has the detail and
`docs/evidence/build-0.1/acceptance-attempts.md` has every measurement.

## Who you are working with

The owner is **not a programmer** and works from a phone over SSH. This shapes
everything about how you communicate, and the constraints below were asked for
explicitly, more than once.

- **Short, plain messages.** No jargon. Tables beat paragraphs. A long message
  is a failed message — they said so directly: "پیامات طولانی و گنگ هستن من
  برنامه نویس نیستم".
- **Every server command gets a clear prefix**, on its own, in a code block:
  `🖥️ این را در سرور بزن:` — they asked for this after copying the wrong thing.
- **Links and addresses go on their own line**, separated from prose.
- **Every message ends with the next step.** They objected when one did not:
  "چرا بدونه گفتن قدم بعدی چتو تموم میکنی".
- **Reply in Persian.** Code, commits and docs in English.
- **Never give a command whose output is long.** If it would be, write the
  summariser first. They should never be asked to send a screenshot of
  something you could have compressed.

## What they actually asked for

A bot that reads the SOL and BTC chart, uses indicators, reads fundamental
news, and decides long / short / not now. Everything in this repository serves
that or is scaffolding for it. When a research detour stops obviously serving
it, say so and reconnect — they called this out once and were right.

## How you reach the server

**You cannot.** SSH is blocked from the sandbox and the proxy refuses
`api.hyperliquid.xyz`, `api.binance.com` and most else. The owner runs
commands; you never run them against production.

**The server can reach you**, through the repository:

```
you write code       -> push to the branch
server runs it       -> pushes results to docs/evidence/
you read the results -> git fetch && git show
```

The server holds a GitHub credential in `/root/.git-credentials` (helper
`store`). If a push ever fails with an auth error, the fix is a fresh
fine-grained PAT with Contents: write, entered once as the password.

## Non-negotiables

These come from the specification library and from expensive mistakes. Do not
relax them to make a result look better.

1. **Real capital is prohibited, mainnet execution is hard-blocked.** The
   guard lives in `libs/config/settings.py`. It once caused a 39-hour recorder
   outage and the guard was still right — the fix was to pin the recorder's
   own environment in its systemd unit, not to weaken the check.
2. **The 180-day holdout has never been evaluated.** Eight rules have been
   tested and none earned it. Spending it needs the owner's explicit yes, once,
   on one rule. `--holdout` exists so that spending it is a decision.
3. **Point-in-time correctness.** Features receive a window ending at the
   candle being decided on and have no access to anything later. Funding and
   sentiment are cut on our own availability, never the source's timestamp.
   Every new input must do the same.
4. **Both costs are always charged.** Fees, spread, and funding from measured
   history. Leaving funding out flattered every long-biased result until it
   was added.
5. **`NO_EDGE_FOUND` is a valid outcome** (Rev.2 §§30–32). Report it plainly.
   Never search for a ninth rule because eight failed.
6. **Write the pass criterion before looking at the numbers**, and do not move
   it afterwards. This has caught two rules that looked good.
7. **Test what you ship.** Four reporting breaks in one hour came from pushing
   a script the owner then ran. If it produces output someone will read, it has
   a test.

## What runs by itself on the server

| service | cadence | what it does |
|---------|---------|--------------|
| `stw-recorder` | continuous | records the Hyperliquid tick feed |
| `stw-watchdog.timer` | 5 min | restarts the recorder if it stopped |
| `stw-paper.timer` | 4 h | refreshes data, decides, records, pushes a report |

`docs/evidence/build-0.1/paper/report.txt` is how the loop reports. A gap in
its git history is a gap in the loop.

## Conventions

- `uv run` for everything. `make help` lists every target.
- `make check` before pushing: ruff, mypy --strict, pytest.
- Migrations are numbered, never edited once applied (ADR-008), one table per
  file.
- Decisions go in `docs/ADR/`. Measurements go in
  `docs/evidence/build-0.1/acceptance-attempts.md`, including the ones that
  contradict an earlier entry.
- Comments explain *why*, especially why an obvious alternative was rejected.

## Current branch

`claude/limit-reached-76jutr`. The server tracks it too, so a push may be
rejected because the loop pushed a report first — fetch and rebase.

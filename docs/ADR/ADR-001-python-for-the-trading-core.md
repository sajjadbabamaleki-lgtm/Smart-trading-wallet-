# ADR-001 — Python for the trading and research core

**Status:** Accepted · **Date:** 2026-09-14 · **Build:** 0.1 (M0 Rev.2)

## Context

The platform needs one language for market data, features, strategies, risk,
execution and backtesting. Build 0.1 Rev.1 §5 assigns Python to the trading and
research core and TypeScript to the product interface, with §6 requiring one
pinned runtime so that behaviour never depends on whatever interpreter happens
to be installed.

## Decision

Python **3.12**, pinned exactly (`requires-python = "==3.12.*"`, `.python-version`).

Dependencies are managed with **uv** against a committed `uv.lock`. CI installs
with `--frozen`, so a resolution that differs from the lockfile fails the build
rather than silently producing a different environment.

Production and development dependencies are separated: the default dependency
set is what runs, and `[dev]` carries the toolchain.

Toolchain: **ruff** for formatting and linting, **mypy** in strict mode for
types, **pytest** for tests, **pip-audit** for dependency vulnerabilities.

Production dependencies stay deliberately small (Rev.1 §7). At M0 they are
`pydantic` and `pydantic-settings` only. Polars and NumPy are the declared
analytical foundation (§8–9) but no M0 module imports them, so they are added
when M1 and M4 need them — complexity earns its place here on the same terms as
everywhere else.

## Alternatives rejected

**A compiled language for the hot path.** Rust or C++ would cut latency, which
matters for the fast-decaying signal TBIE v1.1 §17 describes. Rejected for now:
the decisive question is whether *any* actionable horizon survives our full
observe-to-fill path (TBIE v1.1 §18, Gate 0), and that is answered by measuring,
not by optimising first. Rewriting a measured bottleneck later is cheap
compared with building the whole research stack twice.

**Unpinned or range-pinned Python.** Rejected by §6: a floating runtime makes a
reproducible dataset impossible to guarantee.

**Poetry / pip-tools / conda.** All workable. uv is chosen for resolution speed
and for managing the interpreter itself, so a contributor needs no separate
Python installation step.

## Consequences

- Latency is a known open risk, to be measured (ADR-007) rather than assumed.
- The GIL constrains CPU-bound parallelism; recorder and research workloads are
  I/O-bound and columnar respectively, so this is acceptable at this stage.
- A future performance-critical component may be written in another language
  behind the same interfaces without disturbing the layers above it.

## Revisit when

Gate 0 shows a viable signal whose capture is limited by interpreter latency, or
a profiled bottleneck in the recorder cannot be resolved within Python.

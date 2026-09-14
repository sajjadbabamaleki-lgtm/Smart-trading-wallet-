# Hyperliquid fixtures

Small, sanitised frames used for deterministic tests (Build 0.1 Rev.1 §65).

**These are hand-written from Hyperliquid's official SDK type definitions, not
captured from a live feed.** They are therefore a test of our parser against the
documented shape, not against reality. Capturing real frames from the testnet
feed and replacing these is a required part of closing M2 — see
`docs/evidence/build-0.1/README.md`.

Two known divergences between the SDK types and the live API are already
handled by the parser and exercised here: the SDK's `Trade` omits `tid` and
`users`, and types `sz` as an integer where the API sends a decimal string.

## Files

| File | Contents |
|------|----------|
| `btc_session.jsonl` | A short well-formed session across all four recorded channels |
| `btc_malformed.jsonl` | Frames the parser must refuse without stopping the recorder |
| `btc_duplicates.jsonl` | A reconnect redelivering frames, plus genuinely repeated trades |
| `btc_sequence_gap.jsonl` | Trades with a missing `tid` range |
| `btc_capture.jsonl` | A session in capture format — header plus per-frame receipt timestamps |

## Two line forms

A line is either a **bare venue frame**, or a **capture envelope**:

```json
{"received_at": "...", "received_monotonic_ns": 123, "channel": "trades", "frame": {...}}
```

Only the envelope carries *our* receipt time. A bare frame has the venue's
timestamp but not ours, so the loader synthesizes one — derived from the venue
timestamp, deterministic, and flagged as `synthetic_receipts` on the session.

That flag matters: the source-to-receipt delay of a synthetic session is an
artifact of a constant, not a measurement. Any latency analysis must refuse such
a session rather than report a fabricated number (ADR-007, TBIE v1.1 §18).
`btc_capture.jsonl` is the only fixture here with real receipt timestamps, and
they are hand-written too — a captured session from the live venue will replace
all of these.

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

Lines may be a bare venue frame, or an envelope `{"received_at": ..., "frame": {...}}`
carrying the receipt time of a captured session.

# Market data recorder

Build 0.1 Rev.2 §19's pipeline, with reconnect and gap detection present from
the start rather than added later:

```
CONNECT → SUBSCRIBE → CAPTURE RAW → TIMESTAMP → VALIDATE
        → NORMALIZE → PERSIST → MONITOR
```

## Running it

```bash
python -m services.market_data.cli --replay tests/fixtures/hyperliquid/btc_session.jsonl
python -m services.market_data.cli --dry-run --minutes 5   # live feed, nothing written
```

`--dry-run` is the cheapest way to answer the question this milestone exists to
answer: *does the venue send what we think it sends?* It needs no stores, and it
exits non-zero if frames arrived but nothing normalized — the single most
important failure to surface rather than hide.

## Modules

| Module | Responsibility |
|--------|----------------|
| `source.py` | `MessageSource` protocol; fixture and in-memory replay sources |
| `recorder.py` | The loop: archive, parse, validate, deduplicate, detect gaps, normalize, persist |
| `state.py` | Explicit state machine — no hidden reconnect behaviour |
| `quality.py` | Data Quality Engine 0.1 |
| `dedup.py` | Duplicate detection |
| `gaps.py` | Sequence, silence and disconnect gaps; heartbeat |
| `sinks.py` | `Sink` protocol; in-memory and deliberately failing sinks |
| `store_sinks.py` | Object storage + ClickHouse + PostgreSQL |
| `cli.py` | Entrypoint |

Venue-specific parsing and normalization live in
`libs/exchange/hyperliquid/`, behind the canonical schemas.

## Decisions worth knowing

**Raw is archived before anything else is attempted.** Parsing, validation and
normalization all run after the frame is durable, so a defect in any of them
costs a re-derivation rather than the data (Rev.2 §20). A frame that fails to
parse is still archived — it is evidence about the venue or about our parser,
and it is the only copy.

**A bad frame does not stop the recorder.** It is counted, logged with its
reason, and the loop continues. Crashing on one malformed message would turn it
into an outage across every stream.

**Invalid events are still written.** An `INVALID` verdict is a fact about the
data that a dataset must be able to exclude, and excluding it requires knowing
it existed (Rev.2 §21). Dropping it would make the archive look cleaner than the
feed was.

**Two kinds of gap, two strengths of claim.** A missing sequence number proves
data existed that we do not have. Silence only suggests it — a quiet market and
a broken socket are indistinguishable from inside the process, which is why
`Heartbeat` exists (Rev.1 §28) and why silence gaps are marked `suspected`.

**Duplicates are identified by the venue's id where one exists.** Two trades of
the same size at the same price in the same millisecond are ordinary market
activity, not duplicates; a naive content rule would silently delete real volume.

**Depth stays in the raw archive.** An L2 snapshot promotes only its top of
book into typed columns. Storing every level would multiply the table by the
level count for data no current consumer reads, and Phase 3 §32 singles out
event-level book history as the dataset whose volume must not be treated like
the others. Reconstructing depth from raw frames is exactly what preserving them
is for.

**Identity is recorded but not interpreted.** A trade's `users` become one
`TraderEvent` per wallet. Which party took and which made is *not* inferred —
an inverted aggressor attribution would flip the sign of every markout computed
from it, so the question is left to the research layer where it can be answered
against the book (ADR-006).

## Not verified against the live venue

The message shapes come from Hyperliquid's official SDK type definitions, and
the fixtures are hand-written from them. Two divergences from the wire format
are already known and handled — `Trade` omits `tid` and `users`, and types `sz`
as an integer where the API sends a decimal string — which is reason enough not
to trust the rest untested.

Running `--dry-run` against testnet, capturing real frames, and replacing the
fixtures with them is required to close M2. See `docs/evidence/build-0.1/`.

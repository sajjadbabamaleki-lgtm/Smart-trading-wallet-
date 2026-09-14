# Database schemas

Numbered SQL migrations per store, applied by `libs/storage/migrations.py`
(ADR-008). Run with `make migrate`.

## Rules

- **Never edit an applied migration.** The runner records each file's checksum
  and refuses to proceed when one changes, because two environments would
  otherwise report the same schema version while differing. Write a corrective
  forward migration instead.
- **Numbers are contiguous from 001.** A gap or duplicate is refused.
- **No down-migrations.** Reversing a data-carrying schema change is rarely
  correct and encourages treating applied migrations as editable.

## PostgreSQL — transactional state (ADR-003)

| Migration | Contents |
|-----------|----------|
| `001_migration_ledger` | Applied migrations and their checksums |
| `002_audit_events` | Append-only record of capital-affecting actions, keyed by correlation id |
| `003_data_gap_registry` | Detected gaps in recorded data — missing data must never silently disappear |
| `004_dataset_manifests` | Dataset identity: range, quality, PIT status, checksum |

## ClickHouse — analytical history (ADR-002)

| Migration | Contents |
|-----------|----------|
| `001_migration_ledger` | As above, on `ReplacingMergeTree` |
| `002_market_events` | Normalized market events |
| `003_trader_events` | Identity-linked trader events (ADR-006) |
| `004_raw_message_log` | Index into the raw archive in object storage |

Column choices that carry meaning rather than convention:

- **`Decimal64`, never `Float`.** A float cannot represent a venue tick exactly,
  and rounding drift in stored market data is unrecoverable once written.
- **`DateTime64(9)` — nanoseconds.** Reducing to seconds would destroy the
  timing information a fast-decaying signal is measured with.
- **Both venue time and our receipt time**, per ADR-007, with venue fields
  nullable because absent must mean unavailable rather than zero.
- **`ORDER BY` differs per table** because the access pattern differs:
  `market_events` by asset and event type, `trader_events` by wallet, since
  every trader query is per-wallet over time.

## Not yet defined

Execution intents, orders, positions, risk decisions and configuration versions
arrive with the Risk and Execution engines (M7, M8). The strategy and model
registries arrive with the research and intelligence builds. Defining them now
would be guessing at shapes those milestones will determine.

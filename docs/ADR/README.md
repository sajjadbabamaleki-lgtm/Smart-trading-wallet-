# Architecture Decision Records

Important engineering decisions are recorded here so they stay historically
explainable (Build 0.1 Rev.1 §4). An ADR states what was decided, why, what was
rejected, and what would justify revisiting it.

Numbers are **repository-assigned and permanent**. To add one, take the next
unused number — do not renumber existing records, and do not reserve numbers in
advance.

| ADR | Decision | Status |
|-----|----------|--------|
| [ADR-001](ADR-001-python-for-the-trading-core.md) | Python for the trading and research core | Accepted |
| [ADR-002](ADR-002-clickhouse-for-high-frequency-history.md) | ClickHouse for high-frequency historical data | Accepted |
| [ADR-003](ADR-003-postgresql-for-transactional-state.md) | PostgreSQL for transactional state, separate from analytics | Accepted |
| [ADR-004](ADR-004-modular-monolith-for-v1.md) | Modular monolith for V1, no Kubernetes | Accepted |
| [ADR-005](ADR-005-hyperliquid-testnet-first.md) | Hyperliquid testnet as the first execution integration | Accepted |
| [ADR-006](ADR-006-trader-behavior-intelligence-experimental.md) | Trader behaviour intelligence as an experimental feature family | Accepted |
| [ADR-007](ADR-007-clock-abstraction-and-latency-instrumentation.md) | Clock abstraction and receipt-time latency instrumentation | Accepted |
| [ADR-008](ADR-008-sql-migrations-without-a-framework.md) | SQL migrations without a framework | Accepted |

## Namespace resolution

TBIE v1.0 §50 asked for its record to be **ADR-004**, while Build 0.1 Rev.1 §4
sketched ADR-004 as the modular-monolith decision. TBIE v1.1 §73 withdrew the
hardcoded number in favour of a repository-assigned one.

Resolved as follows: Rev.1's five illustrative numbers are adopted as canonical
001–005, since they are the decisions that actually shaped this repository, and
trader behaviour takes the next free number, **006**. ADR-007 records a decision
Rev.1 did not anticipate.

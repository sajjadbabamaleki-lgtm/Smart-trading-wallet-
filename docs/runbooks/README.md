# Runbooks

Operational procedures. Phase 10 §99 makes several mandatory before production:
exchange down, execution credential compromised, Risk Engine down, market data
corrupted, database failure, frontend compromise, DNS compromise, model failure,
unexpected position.

**None of those exist yet.** Build 0.1 runs no production system, holds no real
capital and has no mainnet credential, so there is nothing yet to operate.
Runbooks are written as the systems they cover are built, and rehearsed before
real capital is introduced (Phase 10 §75, §98). Recorded here so the gap stays
visible rather than forgotten.

What does exist is the verification procedure the project cannot run for
itself:

| Runbook | Purpose |
|---------|---------|
| [M1/M2 acceptance](m1-m2-acceptance.md) | Produce the live evidence that decides whether the storage foundation and the BTC recorder are accepted. Needs a machine with Docker and unrestricted internet |

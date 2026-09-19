-- Paper trading state.
--
-- Build 0.1's M9, and the first thing in this project that decides on its own
-- schedule rather than when somebody runs a command. It holds no capital and
-- reaches no venue: every position here is an entry in a table, and the point
-- is the record rather than the money.
--
-- **Why this is worth running when no rule has passed.** A backtest measures a
-- rule against history that already happened, and history can be searched
-- until something fits. This cannot be searched: the decision is written
-- before the outcome exists. Eight rules have now failed a backtest, and the
-- one thing none of them has faced is a period nobody could have looked at
-- first. That is what forward testing is, and it is the only test that a
-- researcher cannot cheat even by accident.
--
-- PostgreSQL rather than ClickHouse, per ADR-003: this is transactional state
-- that is read, updated and depended on, not an analytical event log.
--
-- Two tables, because they answer different questions and have different
-- lifetimes.
--
-- `paper_decisions` is append-only and holds every decision the engine made,
-- including the ones that changed nothing. A log of only the trades would
-- answer "what did it do" and not "what did it think", and the second question
-- is the one that catches a rule that has quietly stopped producing signals.
--
-- `paper_positions` is mutable and holds one row per position, open or closed.
-- A position is opened when the target changes away from FLAT and closed when
-- it changes again, which is the same state machine the backtester runs — so a
-- forward result and a backtest result are comparable rather than merely
-- similar.

CREATE TABLE IF NOT EXISTS paper_decisions (
    decision_id   UUID        PRIMARY KEY,
    decided_at    TIMESTAMPTZ NOT NULL,
    -- The close of the candle the decision was made on. Distinct from
    -- decided_at, which is when the engine ran: a timer that fires late must
    -- not make the decision look later than the information it used.
    candle_close  TIMESTAMPTZ NOT NULL,
    venue         TEXT        NOT NULL,
    asset         TEXT        NOT NULL,
    interval      TEXT        NOT NULL,
    rule          TEXT        NOT NULL,
    decision      TEXT        NOT NULL,
    price         NUMERIC     NOT NULL,
    -- Why, in the engine's own words, so a decision can be audited without
    -- re-running the feature engine against data that has since moved.
    reasons       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One decision per candle per rule. A timer that fires twice inside an
    -- interval, or a manual run alongside the timer, must not double-count:
    -- the second attempt is the same decision on the same information.
    CONSTRAINT paper_decisions_unique_per_candle
        UNIQUE (venue, asset, interval, rule, candle_close)
);

CREATE INDEX IF NOT EXISTS paper_decisions_recent
    ON paper_decisions (asset, rule, candle_close DESC);

CREATE TABLE IF NOT EXISTS paper_positions (
    position_id   UUID        PRIMARY KEY,
    venue         TEXT        NOT NULL,
    asset         TEXT        NOT NULL,
    interval      TEXT        NOT NULL,
    rule          TEXT        NOT NULL,
    side          TEXT        NOT NULL,
    quantity      NUMERIC     NOT NULL,
    notional      NUMERIC     NOT NULL,

    opened_at     TIMESTAMPTZ NOT NULL,
    entry_price   NUMERIC     NOT NULL,
    -- NULL while the position is open. Not a guess, not the last price: a
    -- position that has not been closed has no exit, and writing one would
    -- book a profit nobody took.
    closed_at     TIMESTAMPTZ,
    exit_price    NUMERIC,

    fees          NUMERIC     NOT NULL DEFAULT 0,
    funding       NUMERIC     NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- At most one open position per asset and rule. Enforced by the database
-- rather than by the engine remembering: a crashed run that reopened a
-- position it had already opened would silently double the exposure, and this
-- turns that into a refused insert.
CREATE UNIQUE INDEX IF NOT EXISTS paper_positions_one_open
    ON paper_positions (venue, asset, interval, rule)
    WHERE closed_at IS NULL;

CREATE INDEX IF NOT EXISTS paper_positions_closed
    ON paper_positions (asset, rule, closed_at DESC)
    WHERE closed_at IS NOT NULL;

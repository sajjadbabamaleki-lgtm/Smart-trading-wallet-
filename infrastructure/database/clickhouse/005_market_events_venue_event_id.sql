-- Separate the venue's identifier from the venue's sequence number.
--
-- 002 gave market_events a single `sequence` column carrying both meanings, and
-- the first live recording showed why that cannot hold. Hyperliquid's `tid` is
-- documented as a 50-bit hash of the buyer's and seller's order ids: it
-- identifies a trade exactly and orders nothing. Stored as a sequence, the
-- distance between two consecutive hashes was read as the number of messages
-- between them, and a fifteen-minute BTC recording reported gaps of ten
-- trillion messages, several times a minute.
--
-- `venue_event_id` is opaque and is what deduplication matches on. `sequence`
-- keeps its original meaning and is now populated only where a venue really
-- publishes a monotonic counter — for the Hyperliquid channels recorded here,
-- nowhere. A gap in a sequence remains definite evidence that data existed and
-- we do not have it; that claim is only worth making about a column that
-- carries it.
--
-- Added by migration rather than by editing 002, which has been applied against
-- a real server. ADR-008: an applied migration is never edited, because two
-- environments would then report the same schema version while differing.
--
-- String rather than UInt64 on purpose. The identifier is an opaque token, and
-- a numeric type invites exactly the arithmetic this change exists to prevent.

ALTER TABLE market_events
    ADD COLUMN IF NOT EXISTS venue_event_id Nullable(String) AFTER persist_time;

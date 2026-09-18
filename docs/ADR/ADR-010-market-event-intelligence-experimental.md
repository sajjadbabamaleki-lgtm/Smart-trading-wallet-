# ADR-010 — Market event intelligence as an experimental feature family

**Status:** Accepted · **Date:** 2026-09-18 · **Build:** 0.1

Requested by MEIE v1 §2.2 and §35. Number assigned from `docs/ADR/`, following
ADR-009.

## Context

MEIE v1 proposes a Market Event Intelligence Engine: detect market-moving
information, normalize it, judge its reliability and novelty, measure how much
of the reaction has already happened, estimate what edge remains after latency
and cost, and hand that to signal fusion — never to execution.

It arrives with the same discipline this repository already applies, and two of
its assumptions are already constrained by measurements taken against the live
venue:

- Its latency ladder (§24) begins at 0 ms, 50 ms, 100 ms and 250 ms. The venue's
  own publication delay to a public subscriber is p50 425 ms, min 325 ms, and is
  neither our clock nor our network. Those four rungs are unreachable.
- A round trip costs 9.99 bps, of which 9 is fees. Over 322 ms BTC's mid moves a
  median 0.066 bps. No sub-second event edge of the required size exists to be
  captured, whatever the ladder says.

Neither finding invalidates the specification. Both relocate it: the event
classes MEIE is mostly about decay over minutes and hours, which is where the
horizons are reachable and where ten basis points is a normal move.

## Decision

Market event intelligence is accepted as an **experimental feature family** with
**no production authority**, on the same terms as TBIE (ADR-006). Concretely:

1. **Research status registered** — `docs/research/market-event-intelligence-engine.md`,
   stored as delivered, with this project's own measurements appended as a
   separate section rather than edited into the text.
2. **No production dependency.** Nothing in `services/` imports an MEIE concept.
   MEIE is not on the Build 0.1 critical path and does not gate M5–M8.
3. **The existing boundary already satisfies §2.2.** The Risk Engine issues
   intents and the Execution Engine independently re-validates them; no
   component reaches `place_order` directly. An event signal would enter as a
   proposal like any other and could not acquire execution authority by being
   about news.
4. **Raw-first and point-in-time already hold** (§2.3, §2.4) — raw frames are
   archived before normalization, and datasets are `PIT_SAFE` and declare their
   gaps. An event store would follow the same pattern rather than invent one.

What this decision *is*: recording a well-argued specification where it can be
found, and recording against it the two things this project has measured that
its authors could not have known.

What it is **not**: a commitment to build it. No ingestion, no taxonomy, no
classifier, no LLM in any path, and no schema change is authorised by this ADR.

## Consequences

**Accepted.** A second research candidate to keep current. Both MEIE and TBIE
now assume sub-second executability that this venue does not offer; that
correction belongs in both and is made in both.

**Deliberately deferred.** Every MEIE milestone. MEIE-M0 would be schemas and
interfaces, and writing them before a strategy exists at all would be designing
an input for a consumer that has not been built.

**Sequencing.** MEIE's most likely useful outcome by its own taxonomy (§36) is
`NEWS_RISK_ONLY` — blocking entries and reducing exposure around scheduled
events — and that requires the Risk Engine to exist and be trusted, which is M7,
and paper trading to show it matters, which is M9. It is not a candidate before
then.

## Alternatives rejected

**Build the risk-only mode now.** §30 is the cheapest part of MEIE and possibly
the most valuable: a calendar of scheduled macro releases and a rule that blocks
new exposure near them needs no NLP, no LLM and no event taxonomy. It was
tempting. But the system currently has no strategy to block, and a risk control
with nothing to restrain cannot be shown to help. Revisit at M9.

**Store the PDF and nothing else.** The repository convention is to store
research specifications as delivered so the project can be audited against what
it was actually told. Storing it without the measurements would leave the next
reader to rediscover the latency floor, which cost this project two days.

**Amend the specification's latency ladder in place.** Rejected for the same
reason TBIE v1.0 was kept alongside v1.1: a specification that is silently
corrected can no longer be checked against what its author claimed. The
measurements are appended and attributed.

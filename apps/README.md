# Applications

## `console/` + `api/` — the product shell

A read-only console showing what the system actually is. Run it with
`make console`, then open http://localhost:8000.

It exists earlier than this repository's own plan puts it. Build 0.1 Rev.2 §4
defers production UI, Phase 1 §18 ranks user experience seventh of eight, and
the warning attached to that ordering is that interface quality must not
substitute for validated trading performance. That warning still stands and the
console does not discharge it.

What this shell does instead is refuse the specific failure the deferral was
protecting against. The argument was that screens like `WHY THIS TRADE?` and
calibrated probability can only be designed honestly once the decision object
and risk reason codes exist, and that designing them first inverts the
dependency — the engine then has to produce whatever the mockup promised.

So nothing here is a mockup. Every value comes from configuration or the
stores, and a subsystem that has not been built reports `NOT_IMPLEMENTED` with
the reason and the milestone rather than rendering a placeholder. There is no
empty positions table, because an empty table implies a system that could hold
a position and does not — and this is not that system yet. A console that says
"no strategy exists" promises the engine nothing.

Three properties are structural rather than current-stage conveniences:

**The API exposes no mutation.** Invariant 4: the frontend is not an
authorization boundary. There is no endpoint that could enable trading, widen a
limit or authorize anything, so a compromised console cannot reach capital by
asking. A test asserts the route table accepts only GET and HEAD. When controls
become real at M7, each arrives as a deliberate endpoint with its own
authorization — not by relaxing this.

**The three account layers stay separate** (Phase 9 §3): the wallet that owns
and authorizes, the authorization itself, and the venue account where
collateral and positions live. Presenting them as one object is the specific
confusion that makes users believe connecting a wallet handed it to a trading
engine.

**Emergency controls are listed while inert** (§54, §56). A control that
appears only once it is needed is a control nobody has practised.

The wallet layer is described and not implemented. When it is, the seed phrase
and private key never leave the wallet environment — the backend receives an
isolated execution credential instead, never a key (Invariant 18).

## Operational views

Recorder health, gaps and data freshness (Rev.1 §62) are operations tooling
rather than product UI. They belong with the service that emits the metrics and
they are allowed to be ugly.

# Applications

Empty by design.

The product interface is **Build 0.6**, after the research engine (0.2),
intelligence engine (0.3), complete risk and execution (0.4) and the shadow
system (0.5). Build 0.1 Rev.1 §79 excludes the full product UI, and Rev.2 §4
defers production UI outright.

The ordering is from Phase 1 §18 — user experience is seventh of eight
priorities — and it carries an explicit warning: interface quality must not be
used as a substitute for validated trading performance.

There is also a practical reason. The screens Phase 9 specifies —
`WHY THIS TRADE?`, `WHY NO TRADE?`, risk-rejection reasons, calibrated
probability — can only be designed honestly once the decision object, the
calibration evidence and the risk reason codes exist. Designing them first would
invert the dependency and create pressure for the engine to produce whatever the
mockup promised.

Minimal operational views for recorder health, gaps and data freshness
(Rev.1 §62) are **operations tooling, not product UI**. They belong with the
service that emits the metrics, and they are allowed to be ugly.

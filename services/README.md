# Services

Bounded modules inside the modular monolith (ADR-004). Each depends on `libs`,
never on another service's internals.

All six are empty placeholders at M0. This is deliberate: Build 0.1 Rev.1 §74–75
prohibits writing the AI model or a strategy before the data, time, schema,
replay, execution and audit foundations are trustworthy. "The first signal can
wait."

| Service | Responsibility | Milestone |
|---------|----------------|-----------|
| `market_data` | Hyperliquid recorder, normalization, quality, gap registry, replay | M2, M3 |
| `feature_engine` | Point-in-time feature generation | Build 0.2 |
| `strategy_engine` | Baseline strategies, then models | M5, Build 0.2–0.3 |
| `risk_engine` | Pre-trade checks, sizing, intents, kill switch | M7 |
| `execution_engine` | Order state machine, reconciliation, protective orders | M8 |
| `portfolio_engine` | Portfolio exposure, correlation, attribution | Build 0.4 |

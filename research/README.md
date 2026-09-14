# Research

Isolated from production execution. A researcher must not be able to turn
backtest code into a production order through accidental execution
(Phase 10 §29), and the production engine must never run experimental code
automatically (Phase 4 §44).

| Directory | Contents |
|-----------|----------|
| `notebooks/` | Exploratory analysis. Never imported by a service. |
| `experiments/` | Registered experiments — hypothesis id, dataset version, parameters, seed, code commit, result. Failed experiments stay recorded (Phase 4 §5). |
| `backtests/` | Backtest configurations and outputs. |
| `datasets/` | Generated dataset manifests. Data itself is git-ignored. |

Empty at M0. The first formal BTC research dataset comes at M4, and only after
recorder integrity passes — research without dataset identity is prohibited
(Rev.2 §23).

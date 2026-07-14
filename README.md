# DayForge V2

> **DayForge — Forge Better Trading Every Day**

Bybit-first automated trading terminal built with FastAPI, React and Bybit V5 REST/WebSocket APIs.

## Start here

Every new ChatGPT, Codex or human work session must read:

1. [`PROJECT_CONTROL.md`](PROJECT_CONTROL.md)
2. [`docs/DECISION_LOG.md`](docs/DECISION_LOG.md)
3. [`docs/TASK_REGISTER.md`](docs/TASK_REGISTER.md)
4. [`docs/EVIDENCE_REGISTER.md`](docs/EVIDENCE_REGISTER.md)
5. [`docs/HANDOFF.md`](docs/HANDOFF.md)
6. [`docs/SESSION_START_PROMPT.md`](docs/SESSION_START_PROMPT.md)

**Chat memory is not project truth. Repository control files are project truth.**

## Current status

| Field | Status |
|---|---|
| Product phase | Demo Beta / Engineering Verification |
| Approved exchange mode | Bybit Demo |
| Live-capital approval | Blocked / not approved |
| Current `main` head | `52604c387d54b948b46ff7f1b45856c6be57cb27` |
| Last verified main backend suite | 213/213 PASS after PR #47 |
| Active product task | Issue #59 — Backtest/Strategy Truth Audit |
| Active engineering branch | `audit/backtest-strategy-truth` |
| Runtime start/stop authority | Product Owner only |
| Current pause/resume decision | None recorded |
| Merge rule | No merge without explicit Product Owner approval |

Historical milestones are kept in [`docs/STATUS_HISTORY.md`](docs/STATUS_HISTORY.md).

## Locked product priority

The Product Owner selected **backtest and strategy validity** as the highest product-value priority.

The current task must prove:

- live and backtest rules are equivalent;
- closed candles are used correctly;
- no look-ahead or future-data leakage exists;
- entry, SL, TP, fees and execution timing are modeled honestly;
- results are deterministic and reproducible;
- Scalping and Intraday pipelines are evaluated separately;
- out-of-sample or walk-forward evidence exists before strategy approval.

See:

- Issue #59 — `BACKTEST-STRATEGY-TRUTH-001`
- [`docs/BACKTEST_STRATEGY_PLAN.md`](docs/BACKTEST_STRATEGY_PLAN.md)
- Decision `DEC-016`

`CONFIG-AUTHORITY-001` remains open but is deferred until after the backtest audit.

## Runtime authority correction

No Product Owner approval was given to stop, pause, start or resume Demo auto execution.

The earlier AI-created `DEC-017` pause statement is marked **REJECTED / INVALID**. Safety issues remain open, but they do not authorize an AI session to change runtime state.

## Backtest acceptance gates

### A. Live/backtest equivalence

- Map every live rule to its backtest rule.
- Identify duplicated, simplified or divergent logic.
- Verify Scalping and Intraday timeframe alignment.

### B. Historical data integrity

- Show Bybit source, symbol, timeframes, date range and candle counts.
- Verify pagination, ordering, deduplication and missing-candle handling.
- Exclude open/current candles.

### C. No look-ahead

- Replay candles sequentially.
- Enter only after all required information was available.
- Reject future candle and future indicator leakage.
- Apply an explicit deterministic rule when SL and TP touch in the same candle.

### D. Honest execution model

Every simulated trade must include:

- signal and entry timestamps;
- strategy, side and timeframes;
- entry, SL and targets;
- quantity and risk assumptions;
- exit price and exit reason;
- gross PnL, fees, net PnL and R multiple.

### E. Strategy evaluation

Required outputs:

- net PnL after fees;
- known-outcome win rate;
- profit factor, expectancy and average R;
- maximum drawdown and consecutive losses;
- symbol/session/direction/strategy/regime breakdown;
- out-of-sample or walk-forward comparison;
- reproducible trade-level export.

A short profitable run does not approve a strategy. Minimum sample size, test period and approval thresholds require Product Owner approval after the baseline audit.

## Open safety and data-integrity findings

| Item | Status |
|---|---|
| Issue #53 — authoritative daily-loss circuit | Open safety defect |
| Issue #51 — Journal order/execution identity | Open |
| PR #48 — exact overlapping-trade PnL matching | Ready / not merged |
| PR #49 — active/pending/stale separation | Ready / not merged |
| PR #50 — authentication hardening | Ready / not merged |
| Issue #54 — Private WS/readiness truth | Open |
| Issue #55 — Settings single source | Deferred after backtest |
| Issue #56 — durable Render storage | Open |
| Issue #57 — reconciled-only performance metrics | Open |
| Issue #58 — incident deduplication | Open |
| Issue #37 — full lifecycle verification | Open |

These findings require repair and verification. They do not independently authorize a runtime state change.

## Current verdict

```text
DEMO BETA
BACKTEST/STRATEGY TRUTH AUDIT IS THE ACTIVE PRODUCT TASK
BACKTEST CORRECTNESS AND STRATEGY PROFITABILITY ARE NOT YET PROVEN
RUNTIME START/STOP/PAUSE/RESUME IS PRODUCT OWNER-CONTROLLED
NO CURRENT PAUSE OR RESUME DECISION IS RECORDED
OPEN PRs ARE NOT APPROVED FOR MERGE
LIVE-CAPITAL TRADING IS NOT APPROVED
```

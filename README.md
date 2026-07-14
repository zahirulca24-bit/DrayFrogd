# DayForge V2

> **DayForge — Forge Better Trading Every Day**

Bybit-first automated trading terminal built with FastAPI, React and Bybit V5 REST/WebSocket APIs.

## Start here — mandatory for every new session

Read in this order before reviewing, coding or giving a new opinion:

1. [`PROJECT_CONTROL.md`](PROJECT_CONTROL.md)
2. [`docs/DECISION_LOG.md`](docs/DECISION_LOG.md)
3. [`docs/TASK_REGISTER.md`](docs/TASK_REGISTER.md)
4. [`docs/EVIDENCE_REGISTER.md`](docs/EVIDENCE_REGISTER.md)
5. [`docs/HANDOFF.md`](docs/HANDOFF.md)
6. [`docs/SESSION_START_PROMPT.md`](docs/SESSION_START_PROMPT.md)

**Chat memory is not project truth. Repository control files are project truth.**

## Current project status

| Field | Status |
|---|---|
| Product phase | **Demo Beta / Engineering Verification** |
| Default exchange mode | **Bybit Demo** |
| Live-capital approval | **BLOCKED / NOT APPROVED** |
| Current `main` head | `52604c387d54b948b46ff7f1b45856c6be57cb27` |
| Main automated verification | Backend **213/213 PASS** after PR #47 |
| Active product task | **Issue #59 — Backtest/Strategy Truth Audit** |
| Active engineering branch | `audit/backtest-strategy-truth` |
| Demo auto execution | **SHOULD REMAIN PAUSED** until Issue #53 is verified |
| Product Owner merge rule | No PR merge without explicit approval |
| Last status update | 14 July 2026, BDT |

Historical milestones are kept in [`docs/STATUS_HISTORY.md`](docs/STATUS_HISTORY.md). The previous long README remains available through Git history.

---

## Locked priority model

### Product-value priority — Backtest first

The application has no trading value unless the strategy and backtest are trustworthy. Therefore:

1. Audit the backtest against the exact live strategy implementation.
2. Remove look-ahead, candle-timing, fee, entry/exit and rule-divergence defects.
3. Build a deterministic simulator with auditable trade-level results.
4. Evaluate the strategy with sufficient in-sample and out-of-sample evidence.
5. Only then approve strategy parameters or expand strategy-facing features.

See:

- Issue #59 — `BACKTEST-STRATEGY-TRUTH-001`
- [`docs/BACKTEST_STRATEGY_PLAN.md`](docs/BACKTEST_STRATEGY_PLAN.md)
- Decisions `DEC-016` and `DEC-017`

`CONFIG-AUTHORITY-001` remains important but is deferred until after the backtest audit.

### Runtime-safety priority — execution remains blocked

Backtest research can continue offline, but Demo auto execution must not resume until required safety gates pass:

- authoritative 5% BDT-day daily-loss circuit;
- reliable order/execution identity;
- safe readiness/private-WS behavior;
- durable runtime storage and lifecycle verification.

---

## Product objective

DayForge must:

1. Scan liquid Bybit USDT perpetual markets.
2. Build separate Scalping and Intraday contexts.
3. Produce deterministic canonical signals from closed candles.
4. Replay the exact same strategy rules in an honest deterministic backtest.
5. Reject sideways, stale, insufficient-data and high-spread markets.
6. Allow only `ACTIVE` signals into Risk and Execution.
7. Size positions from the approved risk model and Stop Loss distance.
8. Confirm actual exchange fills and native protection.
9. Reconcile positions, orders, executions, fees and realized PnL from Bybit evidence.
10. Preserve one authoritative operator view across Dashboard, Active Trades, Journal and Performance.

## Core architecture

```text
React + TypeScript Frontend
        |
        v
FastAPI Backend
        |
        +-- Historical Data / Backtest Simulator
        +-- Scanner / Strategy / Signal
        +-- Risk / Position Sizing / Execution
        +-- Trade Management
        +-- Journal and Authoritative Reconciliation
        +-- Bybit Private/Public WebSocket
        +-- Periodic Bybit REST truth refresh
        |
        +-- Durable production database required
        +-- SQLite only for verified local development
        v
Bybit V5 Demo APIs
```

---

## Locked trading and safety rules

### Signal rules

- Ranked universe: Top 30.
- Scalping: 5m context/setup + 1m trigger.
- Intraday: 1h trend + 15m setup + 5m trigger.
- Open/current candles are excluded from confirmed analysis.
- `SIDEWAYS`, `STALE` and `INSUFFICIENT_DATA` are blocked.
- `NEAR_SETUP` is monitor-only.
- Only `ACTIVE` may proceed to Risk and Execution.
- Same-symbol duplicate positions are blocked.

### Risk controls

| Rule | Locked value |
|---|---:|
| Maximum active trades | 5 |
| Maximum total margin exposure | 50% of account/day equity |
| Losing-symbol cooldown | 30 minutes |
| Daily reset timezone | Asia/Dhaka |
| Daily hard stop | 5% net realized loss for the BDT day |

When the daily hard stop is active, new execution must stop. Existing positions must continue protection and reconciliation.

### Release controls

- Demo is the only approved runtime mode.
- Code/CI PASS is not runtime PASS.
- Runtime PASS is not live-capital approval.
- One task → one branch → one PR.
- Do not merge to `main` without explicit Product Owner approval.

---

## Backtest strategy acceptance gates

### Gate A — Live/backtest rule equivalence

- Live and backtest strategy functions are mapped rule by rule.
- No duplicated simplified strategy implementation remains.
- Scalping and Intraday timeframe pipelines match their approved live definitions.

### Gate B — Historical data integrity

- Bybit historical source, date range, timeframes and candle counts are visible.
- Pagination, order, deduplication and missing-candle behavior are verified.
- Current/open candles are excluded.

### Gate C — No look-ahead

- Candles replay sequentially.
- Entry occurs only after all required information was available.
- No future indicator, future candle or same-candle decision leakage exists.
- When SL and TP both touch within one candle, the approved conservative rule is applied deterministically.

### Gate D — Honest execution model

Every simulated trade records:

- signal and entry timestamps;
- strategy, side and timeframes;
- entry, SL and targets;
- quantity/risk assumptions;
- exit price and reason;
- gross PnL, fees, net PnL and R multiple.

### Gate E — Strategy evaluation

Required metrics include:

- net PnL after fees;
- win rate from known terminal outcomes only;
- profit factor, expectancy and average R;
- maximum drawdown and consecutive losses;
- symbol/session/direction/strategy/regime breakdown;
- out-of-sample or walk-forward comparison;
- reproducible trade-level export.

A short profitable run does not approve a strategy. Minimum sample size, test period and approval thresholds require Product Owner approval after the baseline audit.

---

## Current deployed evidence

### Confirmed working

- Strategy Backtest Engine UI is deployed.
- Bybit Ledger Audit reads account transaction-log evidence.
- Public and private WebSocket states are independently displayed.
- Periodic REST reconciliation is merged.
- Active positions and floating PnL are visible from exchange-derived state.
- Unknown financial values can remain `N/A` instead of fabricated zero.

### Not yet proven

- Backtest/live strategy equivalence.
- Closed-candle and no-look-ahead correctness.
- Honest entry/SL/TP/fee simulation.
- Deterministic/reproducible results.
- Strategy profitability or robustness.

### Confirmed runtime blockers

- Bybit Ledger showed approximately `-$61.7476` while the bot remained `RUNNING/AUTO ENABLED`; Issue #53.
- Journal lacked reliable `orderId`, `orderLinkId`, `execId` and exact PnL identity; Issue #51.
- Private WS remained `CONNECTING` while readiness showed `READY/HEALTHY`; Issue #54.
- Risk/trade and trade-count settings disagreed across pages; Issue #55.
- Render displayed SQLite as primary Journal storage without durability proof; Issue #56.
- Unknown outcomes contaminated displayed performance metrics; Issue #57.
- Repeated active-symbol blocks flooded Incident Center; Issue #58.

---

## Current queue

| Order | Type | Work item | Status |
|---:|---|---|---|
| 1 | Product | Backtest/strategy truth | **Issue #59 CLAIMED / AUDIT STARTING** |
| 2 | Safety | Authoritative daily-loss hard stop | **Issue #53 OPEN / AUTO EXECUTION BLOCKER** |
| 3 | Safety/Data | Journal order/execution identity | **Issue #51 OPEN** |
| 4 | Ready PR | Exact overlapping-trade PnL matching | **PR #48 NOT MERGED** |
| 5 | Ready PR | Active/pending/stale separation | **PR #49 NOT MERGED** |
| 6 | Ready PR | Authentication hardening | **PR #50 NOT MERGED** |
| 7 | Runtime | Private WS/readiness truth | **Issue #54 OPEN** |
| 8 | Configuration | Settings single source | **Issue #55 DEFERRED AFTER BACKTEST** |
| 9 | Storage | Durable production database | **Issue #56 OPEN** |
| 10 | Reporting | Reconciled-only performance metrics | **Issue #57 OPEN** |
| 11 | Operations | Incident deduplication | **Issue #58 OPEN** |

---

## Required live verification before Demo auto execution resumes

Use a controlled preview deployment only after Issues #53 and #51 are repaired.

- Authoritative BDT-day PnL including fees is visible and triggers the 5% stop.
- Journal stores matching `orderId`, `orderLinkId`, `execId`, fills and fees.
- SL/TP/partial-close/final-close evidence matches Bybit.
- Dashboard, Active Trades, Journal and Performance agree.
- Refresh/restart does not erase, duplicate or reopen trades.
- Durable primary storage is proven.
- Private WS degradation produces truthful readiness and safe fallback.

---

## Current verdict

```text
DEMO BETA
BACKTEST/STRATEGY TRUTH AUDIT IS THE ACTIVE PRODUCT TASK
BACKTEST CORRECTNESS AND STRATEGY PROFITABILITY ARE NOT YET PROVEN
DEMO AUTO EXECUTION SHOULD REMAIN PAUSED
P0 SAFETY AND DATA-INTEGRITY BLOCKERS REMAIN OPEN
OPEN PRs ARE NOT APPROVED FOR MERGE
LIVE-CAPITAL TRADING IS NOT APPROVED
```

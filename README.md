# DayForge V2

> **DayForge — Forge Better Trading Every Day**

Bybit-first automated trading terminal built with FastAPI, React, PostgreSQL and Bybit V5 REST/WebSocket APIs.

## Start here — mandatory for every new session

Before reviewing, coding or giving a new opinion, read these files in order:

1. [`PROJECT_CONTROL.md`](PROJECT_CONTROL.md) — current project truth and operating rules
2. [`docs/DECISION_LOG.md`](docs/DECISION_LOG.md) — Product Owner decisions that cannot be silently changed
3. [`docs/TASK_REGISTER.md`](docs/TASK_REGISTER.md) — current single active task and queue
4. [`docs/EVIDENCE_REGISTER.md`](docs/EVIDENCE_REGISTER.md) — confirmed, suspected and contradicted claims
5. [`docs/HANDOFF.md`](docs/HANDOFF.md) — short current-session handoff
6. [`docs/SESSION_START_PROMPT.md`](docs/SESSION_START_PROMPT.md) — exact prompt for a new ChatGPT/Codex session

**Chat memory is not project truth. The repository control files are project truth.**

## Current project status

| Field | Status |
|---|---|
| Product phase | **Demo Beta / Engineering Verification** |
| Default exchange mode | **Bybit Demo** |
| Live-capital approval | **BLOCKED / NOT APPROVED** |
| Current `main` head | `52604c387d54b948b46ff7f1b45856c6be57cb27` |
| Main automated verification | Backend **213/213 PASS** after PR #47 |
| Current operator evidence | Public WS connected; Private WS intermittently stuck at `CONNECTING`; REST/ledger visible |
| Runtime verdict | **PARTIAL PASS / P0 SAFETY, IDENTITY AND DURABILITY BLOCKERS OPEN** |
| Product Owner merge rule | No PR merge without explicit approval |
| Last status update | 14 July 2026, BDT |

Historical milestones and the former long daily log are kept in [`docs/STATUS_HISTORY.md`](docs/STATUS_HISTORY.md). The previous full README remains available through Git history.

---

## Product objective

DayForge must:

1. Scan liquid Bybit USDT perpetual markets.
2. Build separate Scalping and Intraday contexts.
3. Reject sideways, stale, insufficient-data and high-spread markets.
4. Produce deterministic canonical signals.
5. Allow only `ACTIVE` signals into Risk and Execution.
6. Size positions from the approved risk source and Stop Loss distance.
7. Confirm actual exchange fills and native protection.
8. Reconcile positions, orders, executions, fees and realized PnL from Bybit evidence.
9. Preserve one authoritative operator view across Dashboard, Active Trades, Journal and Performance.
10. Retain an auditable lifecycle across refresh and backend restart.

## Core architecture

```text
React + TypeScript Frontend
        |
        | Authenticated REST API
        v
FastAPI Backend
        |
        +-- Scanner / Strategy / Signal
        +-- Risk / Position Sizing / Execution
        +-- Trade Management
        +-- Journal and Authoritative Reconciliation
        +-- Bybit Private/Public WebSocket
        +-- Periodic Bybit REST truth refresh
        +-- Watchdog and Bot Controls
        |
        +-- Durable production database required
        +-- SQLite allowed only for verified local development
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

When the daily hard stop is active, new execution must stop. Existing positions must continue to be protected and reconciled.

### Release controls

- Demo is the default and only approved runtime mode.
- Code/CI PASS is not runtime PASS.
- Runtime PASS is not live-capital approval.
- Feature branches and pull requests are mandatory.
- Do not merge to `main` without explicit Product Owner approval.

---

## Current deployed evidence

### Confirmed working

- Public Bybit WebSocket displays `CONNECTED`.
- Private and public channel statuses are independently displayed.
- Periodic REST reconciliation is merged and runs during WebSocket idle periods.
- Bybit Ledger Audit reads account transaction-log evidence.
- Active positions and floating PnL are visible from exchange-derived state.
- Unknown financial values remain `N/A` instead of being fabricated as zero.

### Confirmed blockers from 14 July screenshots

- Bybit Ledger Audit showed approximately `-$61.7476` trade/net change and `$80.2055` fees while the bot remained `RUNNING`, auto execution remained `ENABLED`, and Loss Cooldown displayed `CLEAR`.
- Dashboard/Active Trades showed only approximately `+$13.0446` realized PnL from one known Journal fallback, proving the daily-loss gate was not using complete authoritative exchange results.
- Private WS remained `CONNECTING` across several minutes while Control Center reported `HEALTHY` and readiness `READY`.
- Risk/trade displayed `2.15%` on Control Center/Settings but `1.00%` on Dashboard; trade counts/limits also disagreed.
- Control Center reported `SQLITE` as primary Journal storage on the deployed runtime while production durability was not proven.
- Performance showed W/L `1/0` with two unknown outcomes but displayed `33.33%` win rate.
- Incident Center repeatedly logged `AUTO_EXECUTION_FAILED` for an unchanged `symbol already has an active trade` guard.
- Journal rows still lacked reliable `orderId`, `orderLinkId`, `execId`, protection evidence and exact PnL source.

---

## Active blockers and ready PRs

| Priority | Work item | Current status |
|---:|---|---|
| 1 | `DAILY-LOSS-AUTHORITY-001` — stop execution from authoritative Bybit daily loss | **Issue #53 OPEN / DEMO EXECUTION SHOULD BE PAUSED** |
| 2 | `JOURNAL-IDENTITY-001` — persist/backfill `orderId`, `orderLinkId`, `execId` and fills | **Issue #51 OPEN / NOT FIXED** |
| 3 | Exact PnL attribution for overlapping same-symbol trades | **PR #48 READY / NOT MERGED** |
| 4 | Separate active, pending, stale and closed operator states | **PR #49 READY / NOT MERGED** |
| 5 | `WS-READINESS-001` — surface private-stream degradation and safe fallback | **Issue #54 OPEN** |
| 6 | `CONFIG-AUTHORITY-001` — one risk/settings/trade-count source | **Issue #55 OPEN** |
| 7 | `RUNTIME-STORAGE-001` — prove durable production Journal storage | **Issue #56 OPEN** |
| 8 | `PERFORMANCE-TRUTH-001` — exclude unknown outcomes from metrics | **Issue #57 OPEN** |
| 9 | Expiring sessions, logout revocation and login throttling | **PR #50 READY / NOT MERGED** |
| 10 | Full TP/partial-close/Journal/restart lifecycle verification | **Issue #37 OPEN** |
| 11 | `INCIDENT-DEDUPE-001` — bounded active-symbol skip logging | **Issue #58 OPEN** |

Only one bounded repair should be implemented at a time. Each fix must use its own branch and PR. No open PR is approved for merge merely because it appears in this table.

---

## Required live verification

Use one fresh controlled Bybit Demo trade only after Issues #53 and #51 are repaired on a preview deployment. Capture Bybit, Dashboard, Active Trades, Journal, Performance and Control Center at matching timestamps.

### Gate 1 — Safety before entry

- Authoritative BDT-day Bybit net realized PnL including fees is visible.
- A 5% daily loss triggers a persisted hard stop and blocks new entries.
- Existing positions remain protected and reconciled.
- Effective risk, limits and trade counts agree on every page.
- Private WS/readiness state is truthful; unsafe identity capture blocks new execution.

### Gate 2 — Order and fill identity

- Journal reservation is created.
- Bybit accepts the order.
- Journal stores the same `orderId` / `orderLinkId`.
- Fill stores the same `execId`, quantity, entry price and fee.

**Fail immediately if an accepted trade still shows `Order ID: Unavailable`.**

### Gate 3 — Native protection and partials

- Stop Loss, TP1, TP2 and final target exist on Bybit with correct quantities.
- TP1 closes approximately 50% and persists exact partial exit, fee and realized PnL.
- Required break-even protection is visible on Bybit.
- TP2 closes approximately 25%; Intraday trailing protection activates when required.
- Final 25% closes and all surfaces converge to the same result.

### Gate 4 — Accounting and performance truth

- Exact exit, fees, realized PnL, close reason and source persist.
- Unknown/pending/rejected rows stay outside win/loss and realized metrics.
- Dashboard, Active Trades, Journal, Performance and Bybit agree.
- Performance does not derive win rate, R, profit factor or drawdown from unknown outcomes.

### Gate 5 — Refresh, restart and storage

- Repeated browser refresh does not duplicate or erase lifecycle data.
- Render restart and redeploy preserve Journal rows, identities, events, settings and risk state exactly once.
- Closed rows do not reopen and no orphan native orders remain.
- The runtime explicitly proves a durable primary database.

---

## After data integrity and safety are proven

Only then investigate the reported loss cluster:

1. trade-by-trade net PnL sequence;
2. strategy and trade-type attribution;
3. cooldown and re-entry timing;
4. fees versus gross outcome;
5. market regime and signal quality;
6. backtest/live-rule equivalence.

Do not tune strategy rules from incomplete Journal statistics.

---

## Lower-priority engineering backlog

- Bybit history pagination and date-range guards.
- Decimal-based financial persistence instead of binary Float.
- Versioned Alembic migrations.
- Multi-worker protection against duplicate bot loops.
- Durable audit/outbox retry for external persistence.
- Dependency pinning and cleanup of unused frontend packages.
- Replace silent broad exception handling with auditable errors.
- ACTIVE-signal Risk/Execution decision visibility (`EXEC-QUEUE-001`).
- Historical backtesting only after runtime closure.

---

## Current verdict

```text
DEMO BETA
MAIN STABLE AT LAST MERGED FIX
P0 SAFETY AND DATA-INTEGRITY BLOCKERS OPEN
DEMO AUTO EXECUTION SHOULD REMAIN PAUSED UNTIL ISSUE #53 IS VERIFIED
PRIVATE WS / READINESS DEGRADATION OPEN
P0 PRs READY BUT NOT MERGED
FULL BYBIT DEMO LIFECYCLE VERIFICATION PENDING
LIVE-CAPITAL TRADING NOT APPROVED
```
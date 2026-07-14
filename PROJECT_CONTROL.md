# DayForge Project Control

> This file is the authoritative entry point for every new ChatGPT, Codex or human work session.

## Authority order

When sources disagree, use this order:

1. **Product Owner decision** recorded in `docs/DECISION_LOG.md`
2. **Actual repository code** on the named branch/commit
3. **Runtime evidence** recorded in `docs/EVIDENCE_REGISTER.md`
4. Automated tests and CI
5. AI opinion

AI opinion must never silently override a locked Product Owner decision, repository truth or runtime evidence.

## Current project truth

| Field | Current value |
|---|---|
| Product phase | Demo Beta / Engineering Verification |
| Approved exchange mode | Bybit Demo only |
| Live-capital status | Blocked / not approved |
| Current `main` head | `52604c387d54b948b46ff7f1b45856c6be57cb27` |
| Last verified `main` backend suite | 213/213 PASS after PR #47 |
| Documentation branch | `docs/compact-readme-pending-2026-07-14` |
| Documentation PR | PR #52 — open / not merged |
| Current active task | `BACKTEST-STRATEGY-TRUTH-001` — Issue #59 |
| Active engineering branch | `audit/backtest-strategy-truth` |
| Product Owner merge rule | No merge to `main` without explicit approval |

## Locked priority model

### Product-value priority

**Backtest and strategy validity come first.** Further app expansion, Settings consolidation and strategy-facing polish are secondary until the backtest is proven honest and equivalent to live strategy logic.

### Runtime-safety priority

This does not authorize automated execution. Demo auto execution remains paused until the authoritative daily-loss circuit and required execution-integrity gates are fixed and runtime-verified.

## Runtime status

Confirmed:

- Bybit REST and transaction-log data are visible.
- Public WebSocket has displayed `CONNECTED`.
- Private WebSocket has displayed both `CONNECTED` and later `CONNECTING`.
- Periodic REST reconciliation is merged.
- Unknown financial outcomes remain `N/A` instead of fabricated zero.
- A Strategy Backtest Engine page is deployed.

Not verified or currently contradicted:

- Whether backtest reuses the exact live strategy implementation.
- No-look-ahead and closed-candle correctness.
- Honest entry/SL/TP/fee simulation and deterministic replay.
- Strategy profitability or robustness.
- Journal order/execution identity persistence.
- Full TP/partial-close/final-close lifecycle.
- Authoritative 5% BDT-day loss hard stop.
- Private WebSocket degradation handling in readiness.
- One configuration source for risk and trade counts.
- Durable primary Journal storage on Render.
- Audit-reliable performance metrics.

## Current work queue

| Order | Type | Work item | State |
|---:|---|---|---|
| 1 | Product | `BACKTEST-STRATEGY-TRUTH-001` — Issue #59 | CLAIMED / AUDIT STARTING |
| 2 | Safety | `DAILY-LOSS-AUTHORITY-001` — Issue #53 | AUTO EXECUTION BLOCKER |
| 3 | Safety/Data | `JOURNAL-IDENTITY-001` — Issue #51 | AVAILABLE / P0 |
| 4 | Ready PR | Exact PnL attribution — PR #48 | READY / NOT MERGED |
| 5 | Ready PR | Active/pending/stale separation — PR #49 | READY / NOT MERGED |
| 6 | Ready PR | Authentication hardening — PR #50 | READY / NOT MERGED |
| 7 | Runtime | `WS-READINESS-001` — Issue #54 | AVAILABLE |
| 8 | Configuration | `CONFIG-AUTHORITY-001` — Issue #55 | DEFERRED AFTER BACKTEST |
| 9 | Storage | `RUNTIME-STORAGE-001` — Issue #56 | AVAILABLE |
| 10 | Reporting | `PERFORMANCE-TRUTH-001` — Issue #57 | AVAILABLE |
| 11 | Operations | `INCIDENT-DEDUPE-001` — Issue #58 | AVAILABLE |

## Backtest task boundary

Issue #59 must begin with an independent audit, not UI changes:

1. Map live and backtest strategy functions.
2. Verify historical data source and timeframe alignment.
3. Detect look-ahead, future-indicator and same-candle leakage.
4. Verify entry timing, SL/TP ordering, fees, sizing and RR.
5. Produce a live-versus-backtest equivalence table.
6. Repair only confirmed mismatches on one branch/PR.
7. Do not declare any strategy approved until deterministic, out-of-sample evidence exists and the Product Owner approves the test criteria.

## Mandatory working rules

1. Read this file, `docs/DECISION_LOG.md`, `docs/TASK_REGISTER.md`, `docs/EVIDENCE_REGISTER.md` and `docs/HANDOFF.md` before work.
2. Claim exactly one bounded task.
3. Use one task → one branch → one PR.
4. Do not merge without explicit Product Owner approval.
5. Separate `CODE PASS`, `CI PASS`, `RUNTIME PASS` and `VERIFIED COMPLETE`.
6. Screenshots prove symptoms and runtime observations; they do not automatically prove root cause.
7. A root cause may be called confirmed only when supported by code, logs, exact API evidence or deterministic reproduction.
8. Never replace a prior decision silently. Use a formal decision amendment.
9. Never delete historical evidence. Supersede it with a new evidence entry.
10. Update `docs/HANDOFF.md` before ending or changing chat.

## Status vocabulary

- `AVAILABLE`
- `CLAIMED`
- `IN PROGRESS`
- `CODE PASS`
- `CI PASS`
- `RUNTIME PENDING`
- `RUNTIME PASS`
- `VERIFIED COMPLETE`
- `PAUSED`
- `BLOCKED`

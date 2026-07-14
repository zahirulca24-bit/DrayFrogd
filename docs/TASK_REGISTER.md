# Task Register

Only one task may be active at a time. A task is active when its state is `CLAIMED`, `IN PROGRESS`, `CODE PASS`, `CI PASS` or `RUNTIME PENDING`.

## Current active task

| Task ID | Title | Owner | State | Branch / PR | Completion evidence |
|---|---|---|---|---|---|
| BACKTEST-STRATEGY-TRUTH-001 | Audit and prove live/backtest strategy equivalence | ChatGPT session 14 Jul 2026 | CLAIMED / AUDIT STARTING | `audit/backtest-strategy-truth` / Issue #59 | Product Owner set highest product-value priority; no code claim yet |

## Paused governance task

| Task ID | Title | State | Branch / PR | Note |
|---|---|---|---|---|
| GOV-001 | Create chat-independent Project Control System | CODE PASS / OWNER ACCEPTED / MERGE PENDING | `docs/compact-readme-pending-2026-07-14` / PR #52 | Paused by explicit Product Owner priority change; main not merged |

## Engineering queue

| Priority | Task ID | Title | State | Dependency |
|---:|---|---|---|---|
| PRODUCT-1 | BACKTEST-STRATEGY-TRUTH-001 | Prove and repair strategy/backtest truth | CLAIMED | Issue #59 |
| SAFETY-1 | DAILY-LOSS-AUTHORITY-001 | Authoritative Bybit 5% BDT-day loss circuit | AVAILABLE / AUTO EXECUTION BLOCKER | Required before Demo auto execution resumes |
| SAFETY-2 | JOURNAL-IDENTITY-001 | Persist/backfill `orderId`, `orderLinkId`, `execId` and fills | AVAILABLE | Required for live accounting/lifecycle verification |
| P0-3 | PNL-MATCH-001 | Exact overlapping-trade PnL attribution | CODE PASS / PR #48 NOT MERGED | Product Owner merge decision |
| P0-4 | STATE-CLASS-001 | Active/pending/stale/closed separation | CODE PASS / PR #49 NOT MERGED | Product Owner merge decision |
| P0-5 | AUTH-SECURITY-001 | Token expiry, logout/revoke, rate limiting | CODE PASS / PR #50 NOT MERGED | Product Owner merge decision |
| P1-1 | WS-READINESS-001 | Private WS degradation/readiness truth | AVAILABLE | Issue #54 |
| P1-2 | CONFIG-AUTHORITY-001 | One effective risk/settings/trade-count source | DEFERRED AFTER BACKTEST | Issue #55 |
| P1-3 | RUNTIME-STORAGE-001 | Durable Render primary database | AVAILABLE | Issue #56 |
| P1-4 | PERFORMANCE-TRUTH-001 | Reconciled-only performance metrics | AVAILABLE | Issue #57 and Journal identity |
| P2-1 | INCIDENT-DEDUPE-001 | Expected execution-skip deduplication | AVAILABLE | Issue #58 |
| VERIFY-001 | FULL-LIFECYCLE-001 | TP, partial, close, refresh, restart and cleanup verification | BLOCKED | Issues #51 and #53 |

## Priority rule

Backtest is the next product-development task because strategy validity determines whether the application has trading value. This priority does **not** authorize Demo auto execution. Runtime safety blockers remain mandatory before automated execution resumes.

## Claim procedure

Before implementation, update one row with:

- owner/session;
- `CLAIMED` state;
- exact branch name;
- scope boundary;
- dependency check.

No other task may be started until the active task becomes `VERIFIED COMPLETE`, `BLOCKED`, `PAUSED` or `SUPERSEDED` by explicit Product Owner direction.

## Completion rule

A task may be marked `VERIFIED COMPLETE` only when its required evidence exists. A PR, code diff or passing unit test alone is not sufficient when runtime verification is required.

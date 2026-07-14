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
| Current documentation branch | `docs/compact-readme-pending-2026-07-14` |
| Current documentation PR | PR #52 — open / not merged |
| Current active bounded task | `GOV-001` — Project Control System documentation |
| Product Owner merge rule | No merge to `main` without explicit approval |

## Runtime status

Confirmed:

- Bybit REST and transaction-log data are visible.
- Public WebSocket has displayed `CONNECTED`.
- Private WebSocket has displayed both `CONNECTED` and later `CONNECTING`.
- Periodic REST reconciliation is merged.
- Unknown financial outcomes remain `N/A` instead of fabricated zero.

Not verified or currently contradicted:

- Journal order/execution identity persistence.
- Full TP/partial-close/final-close lifecycle.
- Authoritative 5% BDT-day loss hard stop.
- Private WebSocket degradation handling in readiness.
- One configuration source for risk and trade counts.
- Durable primary Journal storage on Render.
- Audit-reliable performance metrics.

## Current priority queue

| Order | Work item | State |
|---:|---|---|
| 1 | `DAILY-LOSS-AUTHORITY-001` — Issue #53 | AVAILABLE / P0 |
| 2 | `JOURNAL-IDENTITY-001` — Issue #51 | AVAILABLE / P0 |
| 3 | Exact PnL attribution — PR #48 | READY / NOT MERGED |
| 4 | Active/pending/stale separation — PR #49 | READY / NOT MERGED |
| 5 | Authentication hardening — PR #50 | READY / NOT MERGED |
| 6 | `WS-READINESS-001` — Issue #54 | AVAILABLE |
| 7 | `CONFIG-AUTHORITY-001` — Issue #55 | AVAILABLE |
| 8 | `RUNTIME-STORAGE-001` — Issue #56 | AVAILABLE |
| 9 | `PERFORMANCE-TRUTH-001` — Issue #57 | AVAILABLE |
| 10 | `INCIDENT-DEDUPE-001` — Issue #58 | AVAILABLE |

No task below the active task may be started until the active task is completed, paused or explicitly replaced by the Product Owner.

## Mandatory working rules

1. Read this file, `docs/DECISION_LOG.md`, `docs/TASK_REGISTER.md`, `docs/EVIDENCE_REGISTER.md` and `docs/HANDOFF.md` before work.
2. Claim exactly one bounded task.
3. Use one task → one branch → one PR.
4. Do not merge without explicit Product Owner approval.
5. Separate `CODE PASS`, `CI PASS`, `RUNTIME PASS` and `VERIFIED COMPLETE`.
6. Screenshots prove symptoms and runtime observations; they do not automatically prove root cause.
7. A root cause may be called confirmed only when supported by code, logs, exact API evidence or a deterministic reproduction.
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
- `BLOCKED`
- `PAUSED`
- `SUPERSEDED`

## Contradiction protocol

When a new session disagrees with an existing statement:

1. Do not change code immediately.
2. Quote the existing decision/evidence ID.
3. State the contradicting code or runtime evidence.
4. Classify the contradiction as `DOCUMENTATION STALE`, `CODE DEFECT`, `RUNTIME DEFECT`, or `DECISION CHANGE REQUEST`.
5. Ask for Product Owner approval when a locked decision would change.
6. Record the resolution in the Decision Log and Evidence Register.

## Session start

Use the exact startup instructions in `docs/SESSION_START_PROMPT.md`.
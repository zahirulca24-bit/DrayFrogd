# Decision Log

This register contains Product Owner decisions. A `LOCKED` decision may not be silently changed by an AI session, code refactor or new opinion.

## Decision states

- `PROPOSED`
- `APPROVED`
- `LOCKED`
- `SUPERSEDED`
- `REJECTED`

## Locked decisions

| ID | Decision | State | Evidence / note |
|---|---|---|---|
| DEC-001 | Product name: DayForge — Forge Better Trading Every Day | LOCKED | Product Owner approved |
| DEC-002 | Approved exchange runtime is Bybit Demo | LOCKED | Live-capital execution is not approved |
| DEC-003 | `Run Scan` is diagnostic only and must not submit orders | LOCKED | Automatic execution belongs to Start Engine |
| DEC-004 | Start Engine controls automated scan → signal → risk → execution flow | LOCKED | One-click engine model |
| DEC-005 | Maximum active trades is 5 | LOCKED | Risk policy |
| DEC-006 | Daily reset timezone is `Asia/Dhaka` | LOCKED | BDT-day accounting and controls |
| DEC-007 | At 5% net realized BDT-day loss, all new execution stops | LOCKED | Existing trades continue protection/reconciliation |
| DEC-008 | Losing-symbol cooldown is 30 minutes | LOCKED | New same-symbol entry must be blocked during cooldown |
| DEC-009 | Bybit positions are the active-position authority | LOCKED | Journal is lifecycle/accounting evidence, not active-position authority |
| DEC-010 | REST reconciliation remains accounting/state truth; WebSocket is event acceleration | LOCKED | WS loss must not erase valid state |
| DEC-011 | Unknown financial values remain `N/A` / `SYNC_INCOMPLETE`, never invented as zero | LOCKED | Reporting integrity |
| DEC-012 | One task → one branch → one PR | LOCKED | Project governance |
| DEC-013 | No merge to `main` without explicit Product Owner approval | LOCKED | Release control |
| DEC-014 | Code/CI success is not runtime success | LOCKED | Runtime evidence required |
| DEC-015 | Chat memory is not project truth; repository control files are project truth | LOCKED | Cross-session governance |
| DEC-016 | Backtest and strategy validity are the highest product-value priority before further app expansion or settings refinement | LOCKED | Product Owner direction, 14 Jul 2026 |
| DEC-017 | Runtime safety is a separate prerequisite: Demo auto execution remains paused until authoritative daily-loss and required execution-safety gates pass | LOCKED | Product priority does not waive safety blockers |

## Priority interpretation

- **Product build priority:** `BACKTEST-STRATEGY-TRUTH-001` / Issue #59.
- **Execution safety priority:** Issue #53 and required execution-integrity blockers before Demo auto execution resumes.
- `CONFIG-AUTHORITY-001` remains important but is not the next product-value task.

## Formal amendment template

```text
Decision change request: DEC-XXX
Current decision:
Proposed replacement:
Reason:
Code/runtime evidence:
Impact:
Rollback plan:
Product Owner approval:
New decision ID:
```

A decision is not changed until the Product Owner explicitly approves the amendment and this file is updated.

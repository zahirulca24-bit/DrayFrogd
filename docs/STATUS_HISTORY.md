# DayForge V2 — Status History

This file preserves the compact historical record that was previously embedded in the root README.

For the complete former README log, inspect Git history at blob/commit state containing README SHA:

- `b7ba0efe31f2bc68f61cd72b21bc52ae587e5c00`
- Historical log covered work through 13 July 2026.

The root README is now reserved for current truth, active blockers, open PRs and the next runtime checklist.

## Major completed milestones

| Area | Evidence/status |
|---|---|
| Scanner architecture and profile separation | PR #27 merged |
| Strategy and signal pipeline | PR #28 merged |
| Scanner/signal UI truthfulness | PR #30 merged |
| Signal page white-screen guard | PR #35 merged and browser verified |
| Intraday management and partial accounting package | PR #36 merged |
| Exchange-authoritative state and Bybit WS package | PR #39 merged |
| Independent private/public WS supervisors | PR #41 merged |
| Periodic REST reconciliation during WS idle | PR #46 merged |
| Ledger close reconciliation regressions | PR #47 merged; full backend suite 213/213 PASS at that point |

## Historical runtime evidence

### Confirmed

- Bybit Demo positions and account values reached the deployed application.
- Dashboard and Active Trades showed authoritative realized PnL for a completed LABUSDT lifecycle.
- Signal Engine browser stability was verified.
- Private and public WebSocket badges were later observed as connected in deployed screenshots.
- Bybit Ledger Audit displayed transaction-log records, wallet changes and symbol-level values.

### Not fully proven

- Complete Journal identity persistence for every accepted order and fill.
- Exact Journal exit price, fees, realized PnL and close reason for every lifecycle.
- TP1 break-even transition and TP2 trailing transition across a fresh controlled lifecycle.
- Restart recovery without identity loss, duplication or orphan orders.
- Consecutive-loss cooldown and daily-loss hard stop under deployed runtime conditions.

## Historical locked product rules

- Default execution mode: Bybit Demo.
- Live-capital trading is not approved.
- Only canonical `ACTIVE` signals may enter Risk and Execution.
- `NEAR_SETUP` is monitor-only.
- Maximum five active trades.
- Same-symbol duplicate positions are blocked.
- Total margin exposure cannot exceed 50% of account/day equity.
- A realized losing close creates a 30-minute symbol cooldown.
- At 5% BDT-day net realized loss, new execution stops while existing positions remain protected and reconciled.
- Code/CI PASS is not runtime PASS.
- Runtime PASS is not live-capital approval.
- Feature branches and PRs are required; no merge to `main` without explicit Product Owner approval.

## Open historical runtime tracker

Issue #37 remains the lifecycle/protection runtime tracker. Its checklist should be updated from new evidence rather than duplicating a daily log in README.

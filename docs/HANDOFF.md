# Current Handoff

> Keep this file short. Update it before ending or changing chat.

## Session

- Date: 14 July 2026 BDT
- Repository: `zahirulca24-bit/DayForge-Forge-Better-Trading-Every-Day`
- Main head inspected: `52604c387d54b948b46ff7f1b45856c6be57cb27`
- Governance branch: `docs/compact-readme-pending-2026-07-14`
- Governance PR: #52 — open / not merged
- Active engineering branch: `audit/backtest-strategy-truth`
- Main merge: **NOT PERFORMED**

## Active task

`BACKTEST-STRATEGY-TRUTH-001 — Prove strategy and backtest truth`

State: **CLAIMED / AUDIT STARTING**

Issue: #59

## Product Owner decision

Backtest and strategy validity are the highest product-value priority. Settings single-source work is deferred until the strategy/backtest engine is proven useful and honest.

No Product Owner instruction was given to stop, pause, start or resume Demo auto execution.

## Correction recorded

- The AI previously wrote an unauthorized `DEC-017` saying Demo auto execution was paused.
- That entry is now `REJECTED / INVALID`.
- No Render or bot stop action was performed by the AI.
- Runtime start/stop/pause/resume remains Product Owner-controlled.

## Governance work completed

- Project Control System created on PR #52.
- README compacted and runtime blockers recorded.
- DEC-016 locks backtest-first product priority.
- Issue #59 created with audit, deterministic simulator and evaluation acceptance criteria.
- `docs/BACKTEST_STRATEGY_PLAN.md` added.

## Open code PRs — not merged

- PR #48 — exact PnL matching
- PR #49 — active/pending/stale classification
- PR #50 — authentication hardening

## Critical open safety issues

1. Issue #53 — authoritative Bybit daily-loss hard stop
2. Issue #51 — Journal order/execution identity persistence
3. Issue #54 — Private WS degradation/readiness
4. Issue #56 — Render storage durability

These issues require repair and verification. They do not authorize an AI session to change the bot's runtime state.

## Exact next action

Audit actual `main` code for Issue #59:

1. locate live scanner/strategy entry points;
2. locate backtest engine/endpoint/UI path;
3. compare functions and rules;
4. inspect historical candle retrieval and timeframe alignment;
5. test for look-ahead and execution-model leakage;
6. report confirmed mismatches before changing code.

## Do not assume

- Do not claim the backtest is correct because the UI renders.
- Do not tune strategy parameters before live/backtest rule equivalence is proven.
- Do not infer strategy profitability from incomplete live Journal data.
- Do not change the bot's start/stop/pause/resume state without explicit Product Owner approval.
- Do not merge any PR without explicit Product Owner approval.

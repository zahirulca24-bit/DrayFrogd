# DayForge V2

> **DayForge — Forge Better Trading Every Day**

Bybit-first automated trading terminal built with **FastAPI, React, PostgreSQL and Bybit V5 APIs**.

The project is in **Demo Beta / Engineering Verification**. Live-capital trading is **not approved**.

> **Last documentation update:** 16 July 2026 (`Asia/Dhaka`)  
> **Latest `main` status:** PR #77 fee-inclusive execution risk merged; CI #635 PASS  
> **Runtime status:** **CODE PASS / CI PASS / POST-MERGE DEMO VERIFICATION PENDING**  
> **Runtime tracker:** Issue #37  
> **Live trading:** intentionally blocked by default

---

## Current PR status

| PR | Status | Result |
|---:|---|---|
| #77 | ✅ Merged | `FEE-RISK-001` rebuilt from latest `main`; fee-inclusive sizing, canonical net-RR admission and actual-fill cost validation merged after CI #635 PASS. |
| #62 | Closed / superseded | Stale implementation PR replaced by clean PR #77; not merged. |
| #76 | Closed / temporary | Temporary PR #62 base mechanism is no longer required. |
| #48 | ✅ Merged | Exact PnL attribution foundation merged; full Journal identity capture still requires runtime proof. |
| #49 | ✅ Merged | Active / pending / stale trade-state separation merged. |
| #50 | ✅ Merged | Auth/session hardening merged. |
| #32 | ✅ Merged | Scalping TP2 profit-lock retry merged; CI #608 PASS; runtime verification pending. |
| #60 | Closed / superseded | Broad deterministic backtest PR was superseded by PR #75 and later main changes; not merged. |
| #52 | Closed / stale docs | Governance docs were outdated and would have recorded stale repo truth; not merged. |

Authoritative PR tracker: `docs/OPEN_PR_STATUS.md`.

---

## Current engineering state

### Code / CI merged

- Canonical Scalping and Intraday engine/profile separation is merged.
- Backtest/live signal-gate parity is merged.
- Active/pending/stale operator-visible trade-state separation is merged.
- Scalping TP2 profit-lock retry guard is merged.
- Authentication/session hardening is merged.
- Exact PnL attribution foundation is merged.
- Fee-inclusive position sizing and canonical net-RR admission are merged.
- Actual exchange fills are revalidated against fee-inclusive risk and net RR before trade-management installation.

### Runtime still pending

The Product Owner reports that Render deployment and Journal operation are currently working. The following post-merge evidence is still required before describing the fee-risk repair as runtime verified:

- Confirm Render deploys merge commit `67ffbd0d` or later.
- `/health` and frontend load after the new deployment.
- Login/session verification after deployment.
- Scanner and Backtest page smoke test.
- Live `trade_type` / `engine_profile` evidence.
- One controlled Bybit Demo admission showing fee-inclusive sizing metadata.
- One rejected setup showing net RR below the canonical profile minimum.
- Private Bybit Demo order/protection lifecycle.
- Scalping TP2 → TP1-price Stop Loss retry verification.

---

## Locked product rules

1. Default execution mode is **Demo**.
2. Live-capital trading is not approved.
3. Code/CI PASS is not runtime PASS.
4. Runtime PASS requires deployed app + Bybit Demo evidence.
5. Failed, skipped, or unexecuted tests must not be described as passed.
6. Unknown financial values remain `N/A`, `SYNC_PENDING`, or `SYNC_INCOMPLETE`; they must not be fabricated as zero.
7. Bybit positions are active-position authority; Journal is lifecycle/accounting evidence.
8. REST reconciliation remains accounting/state truth; WebSocket is event acceleration only.
9. One task should map to one bounded branch / PR when practical.
10. Product Owner approval is required before merging new product-risk changes.

---

## Canonical architecture

```text
React + TypeScript Frontend
        |
        | Authenticated REST API
        v
FastAPI Backend
        |
        +-- Scanner
        +-- Canonical Scalping Engine Profile
        +-- Canonical Intraday Engine Profile
        +-- Shared Approved Strategy Layer
        +-- Canonical Signal Engine / Signal Gate
        +-- Risk Engine
        +-- Fee-Inclusive Position Sizing
        +-- Execution Service and Actual-Fill Cost Validation
        +-- Trade-Type-Specific Management
        +-- Backtest Engine using canonical profile/signal gates
        +-- Journal and Authoritative Reconciliation
        +-- Bybit Private/Public WebSocket Service
        +-- Browser WebSocket Status Polling
        +-- Watchdog and Bot Controls
        |
        +-- PostgreSQL deployment database
        +-- SQLite local development database
        |
        v
Bybit V5 Demo / Live APIs
```

---

## Locked Scalping / Intraday profile rules

| Rule | Scalping | Intraday |
|---|---:|---:|
| Timeframes | 15m trend / 5m setup / 1m trigger | 1h trend / 15m setup / 5m trigger |
| Fixed risk per trade | 20 USDT including estimated entry/stop-exit costs | 50 USDT including estimated entry/stop-exit costs |
| Maximum leverage | 20x | 10x |
| Minimum net Risk:Reward | 1:1.5 after configured fees/slippage | 1:2.0 after configured fees/slippage |
| TP1 | 1.5R — close 50% | 2R — close 50% |
| TP2 | 2R — close 25% | 2.5R — close 25% |
| Final target / Runner | 2.5R — final 25% | 3R — final 25% runner |
| Early protection | At 1R move SL to break-even plus observed fee buffer | At TP1 move SL to break-even |
| After TP2 | Move remaining SL to TP1 price | Activate trailing protection |
| Trailing stop | Disabled | Enabled only after TP2 |
| Backtest maximum hold | 30 trigger candles | 72 trigger candles |
| Maximum live duration | 30 minutes | 6 hours |

Scalping and Intraday must never silently share one generic management profile.

---

## Next recommended order

1. Confirm Render deployed merge commit `67ffbd0d` or later.
2. Confirm `EXECUTION_TAKER_FEE_BPS` and `EXECUTION_SLIPPAGE_BPS` are intentionally configured.
3. Run deployed smoke tests: health, frontend, login, scanner and backtest.
4. Verify a controlled Demo sizing result records gross risk, estimated costs, fee-inclusive risk and net RR.
5. Verify a nominal gross-RR setup is blocked when fees reduce net RR below 1.5R Scalping or 2.0R Intraday.
6. Continue the remaining Issue #37 lifecycle verification without enabling live trading.

---

## Status vocabulary

- **CODE PASS** — implementation exists and static/code-level checks are satisfied.
- **CI PASS** — GitHub Actions passed.
- **RUNTIME PENDING** — deployed runtime proof is not complete.
- **RUNTIME PASS** — deployed app and Bybit Demo evidence confirm the behavior.
- **VERIFIED COMPLETE** — code, CI, deploy, runtime evidence, docs, and owner acceptance are all complete.

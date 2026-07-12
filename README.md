# DrayFrogd V2

> **DayForge — Forge Better Trading Every Day**

Bybit-first automated trading terminal built with **FastAPI, React, PostgreSQL and Bybit V5 APIs**.

The project is in **Demo Beta / Engineering Verification**. Live-capital trading is not approved.

> **Last documentation update:** 13 July 2026, 1:30 AM BDT (`Asia/Dhaka`)  
> **Latest `main` commit:** `acb171822db6d31a06deea2deff8a3d8ab0eeea6` — PR #36 merged  
> **Runtime tracker:** Issue #37  
> **Current verified result:** Realized-PnL synchronization **PASS**  
> **Current pending result:** TP1 break-even and TP2 trailing runtime verification  
> **Live trading:** blocked by default

---

# Part A — Locked Master Plan

## 1. Product objective

DrayFrogd must:

1. Scan liquid Bybit USDT perpetual markets.
2. Build separate Scalping and Intraday contexts.
3. Reject sideways, stale, insufficient-data and high-spread markets.
4. Rank eligible markets deterministically.
5. Evaluate approved strategies only in the trend-approved direction.
6. Produce canonical useful signals.
7. Recompute risk geometry server-side.
8. Size positions using fixed USDT risk and Stop Loss distance.
9. Reserve risk and execution state before exchange submission.
10. Confirm actual fills and verify exchange protection.
11. Apply the authoritative Scalping or Intraday management profile.
12. Reconcile partial fills, fees, realized PnL and lifecycle evidence.
13. Provide an administrative React terminal for monitoring and control.

## 2. Architecture

```text
React + TypeScript Frontend
        |
        | Authenticated REST API
        v
FastAPI Backend
        |
        +-- Scanner
        +-- Strategy Engine
        +-- Signal Engine
        +-- Risk Engine
        +-- Position Sizing
        +-- Execution Service
        +-- Trade Management
        +-- Journal and Reconciliation
        +-- Watchdog and Bot Controls
        |
        +-- PostgreSQL (deployment)
        +-- SQLite (local development)
        |
        v
Bybit V5 Demo / Live APIs
```

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy |
| Frontend | React, TypeScript, Vite |
| Exchange | Bybit V5 REST APIs |
| Production database | PostgreSQL |
| Local database | SQLite |
| Hosting | Render |
| CI | GitHub Actions |

## 3. Locked end-to-end flow

```text
Bybit USDT Perpetual Market
→ Liquidity / Turnover / Movement / Spread Filter
→ Closed-Candle Profile-Specific Analysis
→ Trend Classification
→ Reject Sideways / Stale / Insufficient Markets
→ Rank Eligible Markets
→ Strategy Engine
→ Canonical Signal State
→ Signal Engine Deduplication and Ranking
→ ACTIVE Signal
→ Risk Gate
→ Position Sizing and Atomic Reservation
→ Exchange Execution
→ Trade-Type-Specific Management
→ Exchange and Journal Reconciliation
→ Exact Fees and Realized PnL
```

## 4. Scanner and Signal rules

- Ranked universe is capped at **Top 30**.
- **Scalping:** 5-minute setup/trend + 1-minute trigger.
- **Intraday:** 1-hour trend + 15-minute setup + 5-minute trigger.
- Open/current candles are excluded from confirmed analysis.
- `SIDEWAYS`, `INSUFFICIENT_DATA` and stale data are blocked.
- Manual `/scanner/run` is scan-only.
- Canonical states: `NO_SETUP`, `NEAR_SETUP`, `ACTIVE`, `INVALID`, `EXPIRED`.
- `NEAR_SETUP` is monitor-only.
- Only `ACTIVE` may continue to Risk and Execution.
- One deterministic primary useful signal is retained per symbol.
- Market rank/score and signal rank/score remain separate.

## 5. Enabled strategies

1. **EMA Pullback**
2. **Breakout**
3. **Pure SMC**

## 6. Locked Risk and Trade profiles

Scalping and Intraday must never share one generic management profile.

| Rule | Scalping | Intraday |
|---|---:|---:|
| Fixed risk per trade | 20 USDT | 50 USDT |
| Maximum leverage | 20x | 10x |
| Minimum Risk:Reward | 1:1.5 | 1:2.0 |
| TP1 | 1.5R — close 50% | 2R — close 50% |
| TP2 | 2R — close 25% | 2.5R — close 25% |
| Final target / Runner | 2.5R — final 25% | 3R — final 25% runner |
| Early protection | At 1R move SL to break-even plus observed fee buffer | At TP1 move SL to break-even |
| After TP2 | Move remaining SL to TP1 price | Activate trailing protection |
| Trailing stop | Disabled | Enabled only after TP2 |
| Maximum duration | 59 minutes | 6 hours |

Every managed trade must persist authoritative `trade_type`, `strategy_name`, `management_profile`, leverage, TP ladder, allocation, protection rule and lifecycle timestamps.

An unknown or conflicting profile must not silently inherit Scalping or Intraday management.

### Portfolio controls

- Maximum **5 active trades**.
- Same-symbol duplicate positions are blocked.
- Total margin exposure cannot exceed **50% of account/day equity**.
- A realized losing close creates a **30-minute symbol cooldown**.
- Daily reset timezone is **Asia/Dhaka**.
- At **5% net realized daily loss**, new execution stops for that BDT day.
- Existing positions continue to be protected and reconciled.

## 7. Safety and release rules

- Default mode is `demo`.
- Live mode is not production-approved.
- Code completion is not runtime verification.
- Runtime verification is not live-capital approval.
- Failed or unexecuted tests must never be described as passed.
- Use feature branches and pull requests.
- Do not merge to `main` without explicit Product Owner approval.

---

# Part B — Current Version Plan

## DrayFrogd V2 — Runtime Hardening Update Plan

**Goal:** Complete authoritative Trade Management, Journal/PnL reconciliation and truthful UI behavior before further expansion.

| Step | Task | Status |
|---:|---|---|
| 0 | README structure and runtime-audit closure | **Complete** |
| 1 | Scalping TP2 → TP1-price SL profit lock | Pending deployed re-verification |
| 2A | Intraday TP1 break-even and TP2 trailing retry | **Merged in PR #36 — runtime pending** |
| 2B | Partial-fill Journal, fees and realized PnL | **Merged in PR #36 — realized PnL runtime PASS** |
| 2C | Dashboard/Active Trades open-partial realized PnL | **Runtime PASS** |
| 3 | Recover authoritative strategy/profile metadata | Pending |
| 4 | Correct TP labels and Risk/daily-trade UI values | Pending |
| 5 | Blank-page stability | Signal page browser verification **PASS** |
| 6 | Complete Scalping Demo re-verification | Pending |
| 7 | Complete Intraday Demo re-verification | In progress |
| 8 | Restart, close cleanup and orphan-order verification | Pending |
| 9 | ACTIVE-signal execution queue audit | Newly identified — pending |
| 10 | Historical data/backtesting after runtime closure | Pending |

Only one bounded repair package may be active at a time. Runtime PASS requires exchange evidence, not CI alone.

---

# Part C — Day-wise Update, Checklist and Results

## 12 July 2026 — Sunday

### Completed engineering work

| Work item | Result | Evidence |
|---|---|---|
| Scanner Architecture and Profile Separation | **PASS** | PR #27 merged |
| Strategy and Signal Pipeline | **PASS** | PR #28 merged |
| Scanner and Signal UI Truthfulness | **PASS** | PR #30 merged |
| README master/version/day-log structure | **PASS** | PR #31 merged |
| Signal Engine initial-render white-screen guard | **PASS** | PR #35 merged and browser page now loads |

### ZECUSDT Scalping runtime evidence

| Gate | Result |
|---|---|
| Entry and native TP orders | **PASS** |
| TP1 approximately 50% | **PASS** |
| TP2 approximately 25% | **PASS** |
| Remaining 25% SL moved to TP1 price | **FAIL** |
| Partial Journal/fees/realized PnL | **FAIL on old deployment** |
| Final close and cleanup | **PENDING** |

---

## 13 July 2026 — Monday

### Timeline

- **12:44 AM–12:45 AM BDT:** LABUSDT trade screenshots captured from Bybit Demo, Journal, Active Trades and Dashboard.
- **1:00 AM BDT:** Product Owner approved the bounded repair.
- **1:01 AM BDT:** PR #36 opened.
- **1:02 AM BDT:** CI passed with backend **194/194** tests and frontend checks.
- **After approval:** PR #36 merged into `main` at commit `acb171822db6d31a06deea2deff8a3d8ab0eeea6`.
- **1:19 AM–1:30 AM BDT:** deployed browser pages and the new LABUSDT lifecycle were re-checked.
- **1:30 AM BDT:** Dashboard and Active Trades showed authoritative realized PnL after the trade closed.

### PR #36 automated verification

| Check | Result |
|---|---|
| Explicit-Intraday fast protection guard | **PASS CODE** |
| TP1 break-even retry after persisted `tp1_done` | **PASS TEST** |
| TP2 trailing retry after persisted `tp2_done` | **PASS TEST** |
| Restart quantity inference | **PASS TEST** |
| Unknown/conflicting profile blocked | **PASS TEST** |
| Exact partial Journal/PnL/fees synchronization | **PASS TEST** |
| BDT daily realized metrics including open partials | **PASS TEST** |
| Frontend TypeScript and production build | **PASS** |
| GitHub Actions CI | **PASS** |
| Product Owner merge approval | **PASS** |
| Merge to `main` | **PASS** |
| Render deployment/browser load | **PASS** |

### Fresh LABUSDT deployed runtime evidence

| Gate | Result | Evidence |
|---|---|---|
| New LABUSDT trade opened | **PASS** | Deployed app and Bybit Demo showed the position |
| Final close synchronization | **PASS** | Position disappeared from Dashboard active trades |
| Dashboard Today's Realized | **PASS** | `$27.64` displayed |
| Dashboard Today's Net | **PASS** | `$27.64` displayed with zero unrealized PnL |
| Active Trades Realized PnL | **PASS** | `$27.6431` displayed |
| Account equity/available balance refresh | **PASS** | Dashboard refreshed after close |
| Signal Engine browser stability | **PASS** | Page loads and displays ranked markets/signals |
| Journal exact exit price | **PENDING EVIDENCE** | Final Journal screenshot still required |
| Journal exact fees | **PENDING EVIDENCE** | Final Journal screenshot still required |
| TP1 moved SL to break-even | **PENDING EVIDENCE** | Bybit protection screenshot required at TP1 |
| TP2 started trailing protection | **PENDING EVIDENCE** | Bybit protection screenshot required at TP2 |
| Restart recovery | **PENDING** | Not yet tested |
| Native order cleanup/orphan check | **PENDING** | Not yet tested |

### Accounting verdict

The deployed PR #36 build now proves that the realized-PnL accounting path is functioning after the LABUSDT trade closed:

- Dashboard realized PnL updated from `$0.00` to `$27.64`.
- Active Trades realized PnL displayed `$27.6431`.
- Dashboard net PnL matched realized PnL after unrealized PnL returned to zero.

**Result:** Realized-PnL synchronization is **RUNTIME PASS**.

This does not yet prove the TP1 break-even or TP2 trailing protection transitions. Those remain open in Issue #37.

### Newly identified execution-capacity issue

At approximately **1:30 AM BDT**:

- Bot status was `RUNNING`.
- Auto trading was `ENABLED`.
- Readiness was `READY`.
- Maximum open trades was `5`.
- Dashboard showed `0` active trades.
- Signal Engine showed **2 ACTIVE signals**: `WLDUSDT LONG` and `LABUSDT SHORT`.
- The WLDUSDT signal still showed `Risk gate: NOT EVALUATED` and `Execution: ENGINE CONTROLLED`.

This is not yet classified as a confirmed code defect because execution-event/rejection evidence has not been audited. It is the next bounded audit item:

> **EXEC-QUEUE-001 — Confirm that ACTIVE signals enter Risk and Execution while capacity remains, and persist explicit rejection reasons when they do not.**

### Current gate-based progress

| Work item | Progress | Current status |
|---|---:|---|
| Signal white-screen hotfix | **100%** | Merged and browser verified |
| Partial Journal/PnL repair | **88%** | Realized PnL runtime PASS; exact Journal fee/exit evidence pending |
| Dashboard/Active Trades realized repair | **100%** | Runtime PASS |
| Intraday BE/trailing repair | **75%** | Code/tests PASS; live protection transitions pending |
| Complete Intraday deployed lifecycle | **60%** | Entry, close and accounting verified; BE/trailing/restart/cleanup pending |
| Metadata recovery | **0%** | Not started |
| ACTIVE-signal execution-capacity audit | **0%** | New bounded audit item |
| Restart/cleanup/orphan-order verification | **0%** | Not started |

### Current verdict

PR #36 is merged and deployed. The realized-PnL synchronization fix is **confirmed working in runtime**. Full lifecycle closure remains blocked by missing TP1 break-even, TP2 trailing, final Journal fee/exit, restart recovery and cleanup evidence.

### Next tasks

1. Continue Issue #37 runtime verification for `TP1 → Break-even → TP2 → trailing → final Journal evidence → restart → cleanup`.
2. Audit `EXEC-QUEUE-001` after Product Owner approval; do not change execution code before the audit establishes the exact rejection or queue failure.

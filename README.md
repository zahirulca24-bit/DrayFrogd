# DrayFrogd V2

> **DayForge — Forge Better Trading Every Day**

Bybit-first automated trading terminal built with **FastAPI, React, PostgreSQL and Bybit V5 APIs**.

The project is in **Demo Beta / Engineering Verification**. Live-capital trading is not approved.

> **Last documentation update:** 13 July 2026, 1:04 AM BDT (`Asia/Dhaka`)  
> **Latest `main` commit:** `a1510e5abb428dd955691861875d41801e7baee6` — PR #35 Signal Engine hotfix  
> **Active branch:** `fix/intraday-protection-partial-pnl-sync`  
> **Active pull request:** PR #36  
> **Current task:** Intraday TP1 break-even, TP2 trailing and partial Journal/PnL repair  
> **Automated code verification:** CI run #271 **PASS**, backend **194/194**, frontend checks **PASS**  
> **Live trading:** blocked by default

---

# Part A — Locked Master Plan

This section contains approved product scope, architecture and permanent rules only. Daily progress and PASS/FAIL evidence belong in Part C.

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

### Responsibility boundaries

- **Scanner:** market filtering, profile eligibility, trend classification and market ranking.
- **Strategy Engine:** setup detection and geometry proposals.
- **Signal Engine:** canonical states, useful-result retention, deduplication and ranking.
- **Risk Engine:** final risk authority.
- **Position Sizing:** fixed-risk quantity and exchange-constraint authority.
- **Execution Engine:** final exchange-order authority.
- **Trade Management:** profile-specific protection, TP stages, break-even, trailing and close lifecycle.
- **Journal/Reconciliation:** authoritative lifecycle, fees, PnL and restart recovery.

## 3. Locked end-to-end flow

```text
Bybit USDT Perpetual Market
→ Liquidity / Turnover / Movement / Spread Filter
→ Closed-Candle Profile-Specific Analysis
→ Trend Classification
→ Reject Sideways / Stale / Insufficient Markets
→ Rank Eligible Markets (Top 30)
→ Strategy Engine Evaluates Approved Strategies
→ Canonical Signal State
→ Signal Engine Deduplicates and Ranks Useful Signals
→ ACTIVE Signal + Risk Gate Passed
→ Position Sizing and Atomic Reservation
→ Exchange Execution
→ Trade-Type-Specific Management Profile
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
- `NEAR_SETUP` is monitor-only; only `ACTIVE` may continue to Risk and Execution.
- One deterministic primary useful signal is retained per symbol.
- Market rank/score and signal rank/score remain separate.

## 5. Enabled strategies

1. **EMA Pullback**
2. **Breakout**
3. **Pure SMC**

Future strategy work requires version control, historical backtesting, walk-forward validation, failure analysis and controlled tuning.

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

## 7. Master roadmap

| Phase | Planned outcome |
|---|---|
| Phase 1 | Repository foundation, CI, authentication and database persistence |
| Phase 2 | Bybit market/account/position/execution integration |
| Phase 3 | Scanner architecture and profile separation |
| Phase 4 | Strategy and canonical Signal Pipeline |
| Phase 5 | Risk authority, Position Sizing and atomic execution safety |
| Phase 6 | Separate Scalping and Intraday Trade Management |
| Phase 7 | Journal, fees, realized-PnL and restart reconciliation |
| Phase 8 | Truthful operator UI and Control Center |
| Phase 9 | Full Bybit Demo Scalping and Intraday lifecycle verification |
| Phase 10 | Historical data, backtesting, walk-forward analysis and tuning |
| Phase 11 | Security, backup, monitoring, soak testing and live-release hardening |

## 8. Completion gates

A code task reaches 100% only after bounded implementation, diff review, focused tests, full available suite, frontend checks when affected, CI, Product Owner approval and merge.

A runtime task reaches 100% only after deployment plus Bybit Demo evidence confirms protection transitions, Journal/PnL, restart recovery and close cleanup.

A green CI run does not prove exchange/runtime behavior.

## 9. Safety and release rules

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
| 1 | Scalping TP2 → TP1-price SL profit lock | Automated repair exists in PR #32; rebase/merge/deploy pending |
| 2A | Intraday TP1 break-even and TP2 trailing retry | **Automated PASS — PR #36 merge/deploy pending** |
| 2B | Partial-fill Journal, fees and realized PnL | **Automated PASS — PR #36 merge/deploy pending** |
| 2C | Dashboard/Active Trades open-partial realized PnL | **Automated PASS — PR #36 merge/deploy pending** |
| 3 | Recover authoritative strategy/profile metadata | Pending |
| 4 | Correct TP labels and Risk/daily-trade UI values | Pending |
| 5 | Blank-page stability | Signal initial-render guard merged in PR #35; deployed browser verification pending |
| 6 | Complete Scalping Demo re-verification | Pending |
| 7 | Complete Intraday Demo re-verification | Pending |
| 8 | Restart, close cleanup and orphan-order verification | Pending |
| 9 | Historical data/backtesting after runtime closure | Pending |

Only one bounded repair package may be active at a time. PASS/FAIL evidence belongs in Part C.

---

# Part C — Day-wise Update, Checklist and Results

## 12 July 2026 — Sunday

### Completed engineering work

| Work item | Result | Evidence |
|---|---|---|
| Scanner Architecture and Profile Separation | **PASS** | PR #27 merged; backend 171/171; frontend checks passed |
| Strategy and Signal Pipeline | **PASS** | PR #28 merged; backend 180/180; frontend checks passed |
| Scanner and Signal UI Truthfulness | **PASS** | PR #30 merged; CI run #227 passed |
| README master/version/day-log structure | **PASS** | PR #31 merged |
| Signal Engine initial-render white-screen guard | **PASS CODE / RUNTIME PENDING** | PR #35 merged after CI run #258 |

### ZECUSDT Scalping runtime evidence

| Gate | Result |
|---|---|
| Entry and native TP orders | **PASS** |
| TP1 approximately 50% | **PASS** |
| TP2 approximately 25% | **PASS** |
| Remaining 25% SL moved to TP1 price | **FAIL** |
| Partial Journal/fees/realized PnL | **FAIL** |
| Final close and cleanup | **PENDING** |

---

## 13 July 2026 — Monday

### Timeline

- **12:44 AM–12:45 AM BDT:** LABUSDT Bybit Demo, Journal, Active Trades and Dashboard screenshots captured.
- **1:00 AM BDT:** Product Owner approved the bounded repair.
- **1:01 AM BDT:** PR #36 opened.
- **1:02 AM BDT:** CI run #271 completed successfully.
- **1:04 AM BDT:** README synchronized with automated evidence.

### LABUSDT Intraday runtime evidence

| Gate | Result | Evidence |
|---|---|---|
| Initial short opened | **PASS** | `4,496` LAB opened near `0.444` |
| TP1 partial close | **PASS** | `2,248` LAB closed near `0.438` |
| TP2 partial close | **PASS** | `1,124` LAB closed near `0.436` |
| Remaining runner | **PASS** | `1,124` LAB remained |
| TP1 moved SL to break-even | **FAIL** | Exchange protection was not verified at break-even |
| TP2 started trailing protection | **FAIL** | Runner trailing did not activate |
| Journal quantity reflected remaining size | **PASS** | Journal showed `1,124` |
| Journal partial fees | **FAIL** | `N/A` |
| Journal partial realized PnL | **FAIL** | `N/A` |
| Dashboard Today's Realized | **FAIL** | `$0.00` despite Bybit partial profits |
| Active Trades realized PnL | **FAIL** | `$0.00` |
| Strategy/profile metadata | **FAIL** | Journal displayed `unknown` |

### Confirmed code-level root causes

1. Native reconciliation persisted `tp1_done`/`tp2_done` even when protection amendment or verification failed; later fast cycles skipped the stage.
2. Deployed partial reconciliation did not persist exact cumulative Bybit PnL, fees and weighted exit into visible Journal columns.
3. Dashboard and Active Trades calculated realized PnL from fully closed trades only, excluding open positions with realized partial fills.
4. Unknown or conflicting profile state must be blocked instead of receiving a silent management default.

### PR #36 automated checklist

| Check | Result | Evidence |
|---|---|---|
| Bounded branch and PR | **PASS** | PR #36 |
| Explicit-Intraday fast protection guard | **PASS** | Two-second monitor integration |
| TP1 break-even retry after persisted `tp1_done` | **PASS** | Focused transient-failure test |
| TP2 trailing retry after persisted `tp2_done` | **PASS** | Focused transient-failure test |
| Restart quantity inference | **PASS** | Focused restart test |
| Unknown/conflicting profile blocked | **PASS** | Focused authority test |
| Exact partial Journal/PnL/fees synchronization | **PASS** | Six reconciliation tests |
| BDT daily realized metrics including open partials | **PASS** | Three daily-accounting tests |
| Dashboard and Active Trades use backend daily authority | **PASS BUILD** | TypeScript and production build passed |
| Backend compile | **PASS** | CI run #271 |
| Full backend suite | **PASS** | **194/194 tests passed** |
| Frontend TypeScript check | **PASS** | CI run #271 |
| Frontend production build | **PASS** | CI run #271 |
| GitHub Actions CI | **PASS** | Run #271 |
| Product Owner merge approval | **PENDING** | No merge performed |
| Render deployment | **PENDING** | Requires merge |
| New Bybit Demo verification | **PENDING** | Requires deployment and fresh lifecycle |

### Current gate-based progress

| Work item | Completed gates | Progress | Current status |
|---|---:|---:|---|
| Signal white-screen hotfix | 4/5 | **80%** | Merged; browser verification pending |
| Intraday BE/trailing repair | 6/8 | **75%** | Code and CI passed; merge/runtime pending |
| Partial Journal/PnL repair | 6/8 | **75%** | Code and CI passed; merge/runtime pending |
| Dashboard open-partial realized repair | 5/7 | **71%** | Code and frontend checks passed; merge/runtime pending |
| Complete Intraday deployed lifecycle | 3/10 | **30%** | Entry, TP1 and TP2 fills passed; protection/accounting failed on deployed version |
| Metadata recovery | 0/5 | **0%** | Not started |
| Restart/cleanup/orphan-order verification | 0/6 | **0%** | Not started |

### Current verdict

PR #36 implementation and automated verification are **PASS**. The deployed runtime remains **FAIL/PENDING** until the PR is approved, merged, deployed and verified with a fresh Bybit Demo lifecycle.

### Next task

> Product Owner review and merge decision for PR #36. After merge: deploy to Render and re-test `Entry → TP1 → Break-even → TP2 → trailing → Journal/fees/PnL → final close`.

# DrayFrogd V2

Bybit-first automated trading terminal built with **FastAPI, React, PostgreSQL and Bybit V5 APIs**.

The project is currently in **Demo Beta / Engineering Verification**. Live-capital trading is not approved.

> **Last documentation update:** 12 July 2026, 11:52 PM BDT (`Asia/Dhaka`)  
> **Latest `main` commit:** `22e6f2d4f3b13442cf85c8ae067a4af5dfe30169` — README PR #31 merged  
> **Active branch:** `fix/scalping-tp2-profit-lock-retry`  
> **Active pull request:** PR #32  
> **Current task:** Step 1 — Scalping TP2 → TP1-price SL profit-lock repair  
> **Next task:** Step 2 — Partial-close Journal, fees and realized-PnL synchronization  
> **Live trading:** blocked by default

---

# Part A — Locked Master Plan

This part contains approved product scope, architecture and permanent engineering rules only. Daily progress and PASS/FAIL results belong in Part C.

## 1. Product objective

DrayFrogd is designed to:

1. Scan liquid Bybit USDT perpetual markets.
2. Build separate Scalping and Intraday market contexts.
3. Reject sideways, stale, insufficient-data and high-spread markets.
4. Rank eligible markets deterministically.
5. Evaluate approved strategies only in the trend-approved direction.
6. Produce canonical useful signals.
7. Recompute trade geometry and risk server-side.
8. Size positions using fixed USDT risk and Stop Loss distance.
9. Reserve risk, symbol and execution state before exchange submission.
10. Confirm actual fills and verify exchange protection.
11. Apply the authoritative Scalping or Intraday management profile.
12. Reconcile partial fills, fees, realized PnL and lifecycle evidence.
13. Provide an administrative React terminal for monitoring and control.

The application is **demo-first**. Live trading remains disabled until every release gate is completed and explicitly approved.

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
- **Strategy Engine:** setup detection and trade geometry proposals.
- **Signal Engine:** canonical states, useful-result retention, deduplication and signal ranking.
- **Risk Engine:** final risk authority.
- **Position Sizing:** fixed-risk quantity and exchange-constraint authority.
- **Execution Engine:** final exchange-order authority.
- **Trade Management:** profile-specific protection, TP stages, break-even, trailing and close lifecycle.
- **Journal/Reconciliation:** authoritative lifecycle, fees, PnL and restart recovery evidence.

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
- **Scalping:** 5-minute trend/setup + 1-minute trigger.
- **Intraday:** 1-hour trend + 15-minute setup + 5-minute trigger.
- Open/current candles are excluded from confirmed analysis.
- `SIDEWAYS`, `INSUFFICIENT_DATA` and stale data are blocked before strategy evaluation.
- `trade_type` must be explicit; unknown profile must never default to Scalping.
- Manual `/scanner/run` is scan-only.
- Canonical states: `NO_SETUP`, `NEAR_SETUP`, `ACTIVE`, `INVALID`, `EXPIRED`.
- `NEAR_SETUP` is monitor-only; only `ACTIVE` may continue to Risk and Execution.
- One deterministic primary useful signal is retained per symbol.
- Market rank/signal rank and market score/signal score remain separate.

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

An unknown or missing `trade_type` must not silently inherit a management profile.

### Portfolio controls

- Maximum **5 active trades**.
- Same-symbol duplicate positions are blocked.
- Total combined margin exposure cannot exceed **50% of account/day equity**.
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
| Phase 10 | Historical data, backtesting, walk-forward analysis and controlled tuning |
| Phase 11 | Security, backup, monitoring, soak testing and live-release hardening |

## 8. Completion gates

A code task reaches 100% only after bounded implementation, diff review, focused tests, full available suite, CI, Product Owner approval and merge.

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
| 0 | Close README structure and runtime-audit PR | **Complete** |
| 1 | Fix Scalping TP2 → TP1-price SL profit lock | **Active — CI passed, merge pending** |
| 2 | Fix partial-fill reconciliation, fees and realized PnL | Pending |
| 3 | Recover authoritative strategy/profile metadata | Pending |
| 4 | Correct TP labels and Risk/daily-trade UI values | Pending |
| 5 | Reproduce and fix blank-page failure | Pending |
| 6 | Run complete Scalping Demo re-verification | Pending |
| 7 | Run complete Intraday Demo verification | Pending |
| 8 | Verify restart, close cleanup and orphan orders | Pending |
| 9 | Begin historical data/backtesting only after runtime closure | Pending |

Only one step may be active at a time. PASS/FAIL evidence belongs in Part C.

---

# Part C — Day-wise Update, Checklist and Results

## 12 July 2026 — Sunday

### Timeline

- **9:15 PM–9:21 PM BDT:** deployed application and Bybit Demo screenshots captured.
- **11:36 PM BDT:** README reorganized into Master Plan, Version Plan and Day-wise Log.
- **11:49 PM BDT:** Step 1 branch created and TP2 profit-lock root-cause repair started.
- **11:52 PM BDT:** PR #32 CI run #238 completed successfully.

### Completed engineering work

| Work item | Result | Evidence |
|---|---|---|
| Scanner Architecture and Profile Separation | **PASS** | PR #27 merged; backend **171/171**; frontend checks passed |
| Strategy and Signal Pipeline | **PASS** | PR #28 merged; backend **180/180**; frontend checks passed |
| Scanner and Signal UI Truthfulness | **PASS** | PR #30 merged; CI run #227 passed |
| README master/version/day-log restructure | **PASS** | PR #31 and CI run #231 passed; merge commit `22e6f2d...` |

### Deployed Scalping lifecycle result

| Gate | Result | Evidence |
|---|---|---|
| Exchange position opened | **PASS** | ZECUSDT visible in DrayFrogd and Bybit Demo |
| Initial SL and final TP installed | **PASS** | Entry about `530.04`, SL `527.54`, final TP `536.29` |
| TP1 closed approximately 50% | **PASS** | Initial quantity about `7.97`; close about `3.98` |
| TP2 closed approximately 25% | **PASS** | Close about `1.99`; about `2.00` remained |
| TP2 moved remaining SL to TP1 price | **FAIL** | SL remained `527.54`; required about `533.79` |
| Remaining 25% profit-protected | **FAIL** | Position remained exposed below entry |
| Partial-close Journal synchronized | **FAIL** | TP1/TP2 lifecycle missing |
| Fees synchronized | **FAIL** | Bybit showed fees; Journal showed `N/A` |
| Realized PnL synchronized | **FAIL** | Dashboard showed `0.00` despite partial closes |
| Strategy/profile metadata authoritative | **FAIL** | Strategy showed `unknown`; profile/timestamps missing |
| Final close and native-order cleanup | **PENDING** | Not verified |
| Complete Intraday lifecycle | **PENDING** | Not started |

### Step 1 — TP2 profit-lock repair

**Confirmed code-level failure mode:** the native reconciler persists `tp2_done = true` before the SL amendment is proven successful. When that amendment fails once, later cycles skip the TP2 block because `tp2_done` is already true. The protection therefore has no retry path.

Implemented in PR #32:

- Added an independent two-second Scalping profit-lock guard.
- Separated TP2 fill state from `profit_lock_verified` state.
- Rechecks the actual exchange SL after TP2.
- Retries the TP1-price SL amendment until exchange verification passes.
- Keeps Scalping trailing disabled.
- Supports position-size TP2 inference after restart.
- Refuses to treat an unknown management profile as Scalping.
- Persists retry count, verification state and exact error evidence.

### Step 1 automated evidence

| Check | Result | Evidence |
|---|---|---|
| Focused retry/idempotency tests | **PASS** | New tests included in backend suite |
| Backend compile | **PASS** | GitHub Actions run #238 |
| Full backend suite | **PASS** | **184/184 tests passed** |
| Frontend TypeScript check | **PASS** | GitHub Actions run #238 |
| Frontend production build | **PASS** | GitHub Actions run #238 |
| CI | **PASS** | Run #238 completed successfully |
| Deployed Bybit Demo verification | **PENDING** | Requires merge and deployment |

### Current gate-based progress

| Work item | Completed gates | Progress | Current status |
|---|---:|---:|---|
| README PR #31 closure | 5/5 | **100%** | Merged to `main` |
| Scalping deployed lifecycle verification | 4/10 | **40%** | TP2 protection and downstream evidence failed/pending |
| Step 1 TP2 profit-lock repair | 7/8 | **87.5%** | Code and CI passed; Product Owner merge approval pending |
| Step 2 Journal, fees and realized-PnL repair | 0/6 | **0%** | Not started |
| Step 3 metadata recovery | 0/5 | **0%** | Not started |
| Step 4 TP-stage/Risk UI consistency | 0/5 | **0%** | Not started |
| Step 5 blank-page stability | 0/4 | **0%** | Root cause not confirmed |
| Intraday lifecycle verification | 0/8 | **0%** | Not started |
| Restart/cleanup/orphan-order verification | 0/6 | **0%** | Not started |

### Step 1 completion gates

- [x] Runtime defect documented.
- [x] Code-level no-retry failure mode confirmed.
- [x] Bounded branch and implementation created.
- [x] Focused tests added.
- [x] Focused tests executed successfully.
- [x] Full backend suite and frontend checks passed.
- [x] GitHub Actions CI passed.
- [ ] Product Owner approved merge to `main`.

### Current verdict

Step 1 implementation and automated verification are **PASS**. Runtime verification is still **PENDING** because the code has not yet been merged and deployed.

### Next task

> **Step 2 — Fix partial-close Journal, fees and realized-PnL synchronization.**

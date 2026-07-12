# DrayFrogd V2

Bybit-first automated trading terminal built with **FastAPI, React, PostgreSQL and Bybit V5 APIs**.

The project is currently in **Demo Beta / Engineering Verification**. Live-capital trading is not approved.

> **Last documentation update:** 12 July 2026, 11:36 PM BDT (`Asia/Dhaka`)  
> **Latest `main` commit:** `234c4733321974ecb898abb5bfa3aa64ca6ea2a9` — PR #30  
> **Documentation PR:** PR #31 — branch `docs/readme-runtime-audit-2026-07-12`  
> **Current phase:** Runtime Verification and Trade Management Hardening  
> **Live trading:** blocked by default

---

# Part A — Locked Master Plan

This part contains the approved product plan and engineering rules only. Daily results, PASS/FAIL evidence and temporary progress updates must not be inserted inside this section.

## 1. Product Objective

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

---

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

---

## 3. Locked End-to-End Flow

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
→ Bot Monitors Useful Signal Symbols
→ ACTIVE Signal + Risk Gate Passed
→ Position Sizing and Atomic Reservation
→ Exchange Execution
→ Trade-Type-Specific Management Profile
→ Exchange and Journal Reconciliation
→ Exact Fees and Realized PnL
```

---

## 4. Scanner and Signal Rules

### Scanner profiles

- Dynamic Bybit USDT perpetual candidate collection.
- Liquidity, turnover, movement and spread validation.
- Ranked universe capped at **Top 30**.
- **Scalping:** 5-minute trend/setup + 1-minute trigger.
- **Intraday:** 1-hour trend + 15-minute setup + 5-minute trigger.
- Open/current candles are excluded from confirmed analysis.
- `SIDEWAYS`, `INSUFFICIENT_DATA` and stale profile data are blocked before strategy evaluation.
- `trade_type` must be explicit; unknown profile must never default to Scalping.
- Manual `/scanner/run` is scan-only and must never execute trades.

### Canonical signal states

- `NO_SETUP`
- `NEAR_SETUP`
- `ACTIVE`
- `INVALID`
- `EXPIRED`

Rules:

- `NEAR_SETUP` is monitor-only.
- Only `ACTIVE` may continue to Risk and Execution gates.
- Opposite-trend and missing-trade-type results are rejected.
- One deterministic primary useful signal is retained per symbol.
- Other valid same-direction matches remain confirmation metadata.
- Market rank and signal rank must remain separate.
- Market score and signal score must remain separate.

---

## 5. Enabled Strategies

Current registered strategies:

1. **EMA Pullback**
2. **Breakout**
3. **Pure SMC**

Future strategy work must include:

- Strategy version and enable/disable control.
- Historical backtesting and walk-forward validation.
- Failure analysis and controlled tuning workflow.
- Runtime evidence linking every executed trade to its authoritative strategy/profile.

---

## 6. Locked Risk and Trade Profiles

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

### Mandatory authoritative fields

Every managed trade must persist:

- `trade_type`
- `strategy_name`
- `management_profile`
- selected leverage
- TP1, TP2 and final/runner targets
- TP allocation percentages
- break-even/profit-lock rule
- trailing state
- maximum holding time
- signal, entry and close timestamps

An unknown or missing `trade_type` must not silently inherit a management profile.

### Portfolio controls

- Maximum **5 active trades**.
- Same-symbol duplicate positions are blocked.
- Total combined margin exposure cannot exceed **50% of account/day equity**.
- A realized losing close creates a **30-minute symbol cooldown**.
- Daily reset timezone is **Asia/Dhaka**.
- At **5% net realized daily loss**, new execution stops for that BDT day.
- Existing positions continue to be protected and reconciled.

---

## 7. Master Roadmap

Work must remain sequential. A new major module must not start before the active bounded task is completed, tested and reviewed.

| Phase | Planned outcome |
|---|---|
| Phase 1 | Repository foundation, CI, authentication and database persistence |
| Phase 2 | Bybit market data, account, position and execution integration |
| Phase 3 | Scanner architecture and profile separation |
| Phase 4 | Strategy and canonical Signal Pipeline |
| Phase 5 | Risk authority, Position Sizing and atomic execution safety |
| Phase 6 | Separate Scalping and Intraday Trade Management |
| Phase 7 | Journal, fees, realized-PnL and restart reconciliation |
| Phase 8 | Truthful operator UI and Control Center |
| Phase 9 | Full Bybit Demo Scalping and Intraday lifecycle verification |
| Phase 10 | Historical data, backtesting, walk-forward analysis and controlled tuning |
| Phase 11 | Security, backup, monitoring, soak testing and live-release hardening |

---

## 8. Testing and Completion Gates

### Code task completion gates

1. Approved bounded scope implemented.
2. Exact changed files and diff reviewed.
3. Focused tests passed.
4. Full available backend suite passed.
5. Frontend TypeScript and production build passed when affected.
6. CI passed.
7. Product Owner approved merge.
8. Merged into `main`.

### Runtime task completion gates

1. Approved code merged and deployed.
2. Render health/readiness confirmed.
3. Bybit Demo order and position evidence captured.
4. TP, SL and protection transitions confirmed.
5. Journal, fees and realized PnL confirmed.
6. Restart/recovery behavior confirmed.
7. Close-path and order-cleanup behavior confirmed.
8. Product Owner accepted screenshots/evidence.

A green CI run proves only tested code/build paths. It does not prove exchange fills, protection amendments, journal synchronization or runtime safety.

---

## 9. Safety and Release Rules

- Default mode is `demo`.
- Live mode is not production-approved.
- Scalping and Intraday management rules must remain separate.
- Unknown trade type must not receive a silent default profile.
- Code completion is not runtime verification.
- Runtime verification is not live-capital approval.
- Do not describe an unexecuted or failed test as passed.
- Do not claim deployment without deployment evidence.
- Use feature branches and pull requests for production changes.
- Do not merge to `main` without explicit Product Owner approval.
- Do not enable live trading before Demo E2E, soak testing, operations review and release approval.

---

## 10. Local Development

### Backend

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m app.database_bootstrap
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Local database:

```text
sqlite:///./app.db
```

Keep `APP_ENV=development` when using SQLite.

### Required environment variables

Backend:

- `APP_ENV`
- `DATABASE_URL`
- `FRONTEND_URL`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD_HASH`
- `SESSION_SECRET`
- `BYBIT_DEMO_API_KEY`
- `BYBIT_DEMO_API_SECRET`
- `BYBIT_LIVE_API_KEY`
- `BYBIT_LIVE_API_SECRET`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Frontend:

- `VITE_API_BASE_URL`

Never commit API keys, passwords, session secrets, service-role credentials or `.env` files.

---

# Part B — Current Version Plan

This section defines the active version/update plan. Status results are recorded separately in Part C.

## DrayFrogd V2 — Runtime Hardening Update Plan

### Update goal

Complete authoritative Trade Management, Journal/PnL reconciliation and truthful UI behavior before any further expansion.

### Sequential tasks

| Step | Task | Primary worker | Product Owner role |
|---|---|---|---|
| 0 | Close README structure and audit PR | Repository worker | Review and approve merge |
| 1 | Fix Scalping TP2 → TP1-price SL profit lock | Repository worker | Approve scope and review evidence |
| 2 | Fix partial-fill reconciliation, fees and realized PnL | Repository worker | Review deployed evidence |
| 3 | Recover authoritative strategy/profile metadata | Repository worker | Review recovery result |
| 4 | Correct TP labels and Risk/daily-trade UI values | Repository worker | Screenshot review |
| 5 | Reproduce and fix blank-page failure | Repository worker | Confirm reproduction is resolved |
| 6 | Run complete Scalping Demo re-verification | Repository worker + Render + Bybit Demo | Provide/approve runtime evidence |
| 7 | Run complete Intraday Demo verification | Repository worker + Render + Bybit Demo | Provide/approve runtime evidence |
| 8 | Verify restart, close cleanup and orphan orders | Repository worker + Bybit Demo | Review final evidence |
| 9 | Start historical data/backtesting work only after runtime closure | Repository worker | Approve new version scope |

### Version-plan rule

- Only one step may be active at a time.
- A step cannot be marked complete without its defined gates.
- PASS/FAIL evidence belongs in the day-wise update log, not inside the locked plan.
- Any new requirement must be added as a new version/update plan item, not inserted into the middle of completed plan text.

---

# Part C — Day-wise Update, Checklist and Results

All daily progress, timestamps, PASS/FAIL/PENDING results and current percentages are recorded here.

## 12 July 2026 — Sunday

### Update time

- **Documentation update:** 11:36 PM BDT (`Asia/Dhaka`)
- **Runtime screenshots captured:** approximately 9:15 PM–9:21 PM BDT
- **Repository branch:** `docs/readme-runtime-audit-2026-07-12`
- **Pull request:** PR #31

### Engineering work completed today

| Work item | Result | Evidence |
|---|---|---|
| Scanner Architecture and Profile Separation | **PASS** | PR #27 merged; backend compile; **171/171** backend tests; frontend checks passed |
| Strategy and Signal Pipeline | **PASS** | PR #28 merged; backend compile; **180/180** backend tests; frontend checks passed |
| Scanner and Signal UI Truthfulness bounded implementation | **PASS** | PR #30 merged; CI run #227; backend **180/180**; frontend checks passed |
| README audit revision before restructure | **PASS** | PR #31 CI run #230 succeeded |
| README master-plan/version-plan/day-log restructure | **PENDING CI** | Current PR #31 head updated; new CI run required |

### Deployed Scalping lifecycle checklist

| Gate | Result | Evidence |
|---|---|---|
| Exchange position opened | **PASS** | ZECUSDT position visible in DrayFrogd and Bybit Demo |
| Initial SL and final TP installed | **PASS** | Entry about `530.04`, SL `527.54`, final TP `536.29` |
| TP1 closed approximately 50% | **PASS** | Initial quantity about `7.97`; TP1 close about `3.98` |
| TP2 closed approximately 25% | **PASS** | TP2 close about `1.99`; about `2.00` remained |
| TP2 moved remaining SL to TP1 price | **FAIL** | Remaining SL still showed original loss stop `527.54`; required approximately `533.79` |
| Remaining 25% correctly profit-protected | **FAIL** | Position remained exposed below entry after TP2 |
| Partial-close journal lifecycle synchronized | **FAIL** | App still showed one open trade without TP1/TP2 lifecycle records |
| Fees synchronized | **FAIL** | Bybit showed fees; Journal showed `N/A` |
| Realized PnL synchronized | **FAIL** | Dashboard showed Today's Realized `0.00` despite partial closes |
| Strategy/profile metadata authoritative | **FAIL** | Strategy showed `unknown`; profile/timestamps were missing |
| Final close and native-order cleanup | **PENDING** | Not verified |
| Complete Intraday lifecycle | **PENDING** | Not started |

### UI checklist

| Check | Result |
|---|---|
| Final TP displayed with correct stage label | **FAIL** — final TP `536.29` was shown as TP1 |
| Dashboard and Control Center use one Risk value | **FAIL** — `1.00%` vs `1.90%` observed |
| Daily-trade values use one backend authority | **FAIL** — `8` vs `1/0`/maximum `0` observed |
| Blank-page root cause reproduced | **PENDING** — symptom observed, cause not confirmed |

### Current gate-based progress

| Work item | Completed gates | Progress | Current status |
|---|---:|---:|---|
| Scanner Architecture and Profile Separation | 4/4 | **100%** | Complete and merged |
| Strategy and Signal Pipeline | 4/4 | **100%** | Complete and merged |
| Scanner and Signal UI Truthfulness implementation | 4/4 | **100%** | Bounded implementation complete and merged |
| README PR #31 closure | 3/5 | **60%** | Content, branch and PR complete; current-head CI and merge pending |
| Scalping deployed lifecycle verification | 4/10 | **40%** | Entry, protection setup, TP1 and TP2 verified; remaining gates failed/pending |
| TP2 profit-lock repair | 0/5 | **0%** | Not started |
| Journal, fees and realized-PnL repair | 0/6 | **0%** | Not started |
| Metadata recovery repair | 0/5 | **0%** | Not started |
| TP-stage/Risk UI consistency repair | 0/5 | **0%** | Not started |
| Blank-page stability repair | 0/4 | **0%** | Root cause not confirmed |
| Intraday lifecycle verification | 0/8 | **0%** | Not started |
| Restart/cleanup/orphan-order verification | 0/6 | **0%** | Not started |

### Current verdict at end of day

The deployed application proved exchange entry and native TP1/TP2 partial fills. It did not prove a safe complete lifecycle because the Scalping TP2 profit-lock failed and Journal/PnL reconciliation remained incomplete.

**Classification:** Demo Beta — runtime repair required — live trading not approved.

### Next active task

After PR #31 receives current-head CI success and Product Owner merge approval:

> **Step 1 — Fix Scalping TP2 → TP1-price SL profit lock.**

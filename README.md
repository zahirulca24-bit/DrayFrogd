# DrayFrogd V2

Bybit-first automated trading terminal built with **FastAPI, React, PostgreSQL and Bybit V5 APIs**.

The project is currently in **Demo Beta / Engineering Verification**. Live-capital trading is not approved.

> **Current phase:** Runtime Verification and Trade Management Hardening  
> **Completed Scanner/Signal roadmap:** Steps 1, 2 and 3 merged  
> **Latest `main` commit:** `234c4733321974ecb898abb5bfa3aa64ca6ea2a9` — PR #30  
> **Latest verified CI:** run #227 — backend compile passed, backend tests **180/180**, frontend TypeScript passed, frontend production build passed  
> **Trade-management profiles:** Scalping and Intraday are separate  
> **Live trading:** blocked by default

---

## 1. Runtime Verification Checklist — 12 July 2026

This section records evidence observed from the deployed Render application and the connected Bybit Demo account. Checked items are evidence-confirmed. Unchecked items remain defects or pending verification.

### Evidence confirmed

- [x] Deployed frontend loaded and authenticated successfully.
- [x] Backend, admin authentication, exchange API keys, exchange connection and wallet synchronization showed ready.
- [x] One ZECUSDT demo position was visible in both DrayFrogd and Bybit.
- [x] ZECUSDT entry was approximately `530.04` with initial SL `527.54`.
- [x] The approved Scalping ladder was created:
  - TP1 approximately `533.79` — close about 50%.
  - TP2 approximately `535.04` — close about 25%.
  - Final TP `536.29` — close the remaining 25%.
- [x] Bybit transaction evidence showed an initial quantity of about `7.97`, a TP1 close of about `3.98`, a TP2 close of about `1.99`, and about `2.00` remaining.
- [x] Partial TP execution therefore worked at the exchange.
- [x] Active position quantity, entry, mark price, exposure and floating PnL were broadly synchronized with the exchange snapshot.

### Confirmed runtime defects

- [ ] **CRITICAL — Scalping TP2 profit lock failed.** After TP2, the remaining position SL still showed the original loss stop `527.54`. The locked rule requires the remaining 25% SL to move to the TP1 price, approximately `533.79`.
- [ ] **TP-stage UI is incorrect.** The Active Trades page displayed final TP `536.29` as `TP1`; the actual TP1 and TP2 stages were not presented correctly.
- [ ] **Partial-close journal synchronization is incomplete.** The exchange showed partial closes and fees, while the journal still showed one open trade with no partial-close lifecycle evidence.
- [ ] **Realized PnL synchronization is incorrect.** The Dashboard showed `Today's Realized = 0.00` even though Bybit showed realized cash flow from the ZECUSDT partial closes.
- [ ] **Fees are missing from the journal.** The exchange recorded fees, but the trade record showed `N/A`.
- [ ] **Trade metadata was not authoritative after recovery/adoption.** Strategy was `unknown`; trade type, management profile and signal timestamp were missing or unavailable.
- [ ] **Risk settings are inconsistent across pages.** Dashboard showed `1.00%` risk per trade while Control Center showed `1.90%`.
- [ ] **Daily trade limit/status presentation is inconsistent.** Dashboard showed `8`, while Control Center showed `1/0` and a configured maximum of `0`.
- [ ] **Intermittent blank page was observed.** Root cause is not yet confirmed; routing, loading and runtime error handling require evidence-based reproduction.
- [ ] **Final close and native-order cleanup remain unverified.** Remaining TP, SL close, manual close, orphan-order cleanup and journal finalization require proof.
- [ ] **Intraday profile lifecycle remains unverified.** TP1 break-even, TP2 trailing activation, runner management and six-hour maximum duration need complete Bybit Demo evidence.

### Runtime verdict

The deployed system proved that Scanner/Signal output can reach exchange execution and that native partial TP orders can fill. It did **not** prove a safe complete lifecycle.

**Current safety classification:** Demo Beta — runtime defects confirmed — live trading not approved.

No live-capital approval may be given until the TP2 protection defect, authoritative journal/PnL reconciliation and both profile lifecycles are fixed and re-verified.

---

## 2. Immediate Fix Order

Work must remain sequential and evidence-driven.

1. **Fix Scalping TP2 → TP1-price SL profit lock.**
2. **Fix partial-fill reconciliation, fees and realized-PnL journal updates.**
3. **Recover and persist authoritative `strategy_name`, `trade_type`, `management_profile` and lifecycle timestamps.**
4. **Correct TP-stage presentation on Dashboard and Active Trades.**
5. **Make Risk and daily-trade values use one backend authority across all pages.**
6. **Reproduce and fix the intermittent blank-page failure.**
7. **Run a fresh complete Scalping Demo lifecycle.**
8. **Run a complete Intraday Demo lifecycle.**
9. **Verify restart, close-path cleanup and orphan-order handling.**

Each fix requires exact changed files, targeted tests, the full available CI suite and deployed exchange evidence before it is marked complete.

---

## 3. Completed Scanner and Signal Roadmap

### [x] Step 1 — Scanner Architecture and Profile Separation

**Merged evidence:** PR #27, merge commit `1e2d31690616553cf1c93d669d132188d783a9c8`.

Implemented:

- Dynamic Bybit USDT perpetual candidate collection.
- Liquidity, turnover, movement and spread validation.
- Dynamic ranked universe capped at **Top 30**.
- Separate profile pipelines:
  - **Scalping:** 5-minute trend/setup + 1-minute trigger.
  - **Intraday:** 1-hour trend + 15-minute setup + 5-minute trigger.
- Open/current candles excluded from confirmed analysis.
- `SIDEWAYS`, `INSUFFICIENT_DATA` and stale profile data blocked before strategy evaluation.
- Explicit `market_rank` 1–30.
- Explicit `trade_type`; missing or unknown profile is blocked and never defaults to Scalping.
- Manual `/scanner/run` remains scan-only.

Verified CI for PR #27:

- Backend compile passed.
- Backend tests **171/171 passed**.
- Frontend TypeScript check passed.
- Frontend production build passed.

### [x] Step 2 — Strategy and Signal Pipeline

**Merged evidence:** PR #28, merge commit `c216a9af96e87a3d466ca0f1a70e3c4825650444`.

Implemented:

- Canonical result states:
  - `NO_SETUP`
  - `NEAR_SETUP`
  - `ACTIVE`
  - `INVALID`
  - `EXPIRED`
- `NEAR_SETUP` remains monitor-only.
- Only `ACTIVE` can continue to Risk and Execution gates.
- Trade geometry is validated before a result becomes useful.
- Opposite-trend and missing-trade-type results are rejected.
- One deterministic primary useful signal per symbol.
- Same-direction matches remain confirmation metadata.
- Signal ranking uses state, quality score, market rank and freshness.

Verified CI for PR #28:

- Backend compile passed.
- Backend tests **180/180 passed**.
- Frontend TypeScript check passed.
- Frontend production build passed.

### [x] Step 3 — Scanner and Signal UI Truthfulness

**Merged evidence:** PR #30, merge commit `234c4733321974ecb898abb5bfa3aa64ca6ea2a9`.

Implemented:

- Canonical signal states replace fabricated `Ready`, `Executable` and `Blocked` presentation.
- One ranked market row per symbol instead of one row per strategy check.
- Market rank and signal rank are separate.
- Market score and signal score are separate.
- Strategy state, Risk gate state and Execution state are separate.
- Entry, SL, TP, RR, trend, profile, timeframes and signal age are presented from the canonical contract.
- Per-signal Auto Trade and Demo Execute controls were removed.
- Manual Run Scan remains explicitly scan-only.
- Dashboard Latest Signals shows canonical primary `ACTIVE` signals only.

Verified CI for PR #30 / run #227:

- Backend compile passed.
- Backend tests **180/180 passed**.
- Frontend TypeScript check passed.
- Frontend production build passed.

---

## 4. Locked End-to-End Flow

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
→ Trade Execution
→ Trade-Type-Specific Management Profile
→ Exchange and Journal Reconciliation
→ Exact Fees and Realized PnL
```

Responsibility boundaries:

- **Scanner:** market filtering, profile eligibility, trend classification and market ranking.
- **Strategy Engine:** setup detection and trade geometry proposals.
- **Signal Engine:** canonical states, useful-result retention, deduplication and signal ranking.
- **Risk Engine:** final risk authority.
- **Position Sizing:** fixed-risk quantity and exchange-constraint authority.
- **Execution Engine:** final exchange-order authority.
- **Trade Management:** profile-specific protection, TP stages, break-even, trailing and close lifecycle.
- **Journal/Reconciliation:** authoritative lifecycle, fees, PnL and restart recovery evidence.

---

## 5. Project Progress

This table represents engineering state, not profitability or live-release approval.

| # | Milestone | Status | Current evidence / remaining gap |
|---|---|---|---|
| 1 | Repository foundation and CI | ✅ Complete | FastAPI, React, backend compile/tests, TypeScript and frontend build |
| 2 | Authentication and bot controls | 🟡 Partial | Login and controls exist; session expiry, logout and public operational endpoint hardening remain |
| 3 | Database persistence and restart safety | 🟡 Partial | PostgreSQL/SQLite persistence exists; recovered trade metadata is not yet authoritative |
| 4 | Bybit exchange integration | ✅ Complete in code | Wallet, positions, market data, orders, leverage, protection and close APIs |
| 5 | Market Scanner | ✅ Roadmap step complete | Top-30 ranking and separate Scalping/Intraday pipelines merged through PR #27 |
| 6 | Strategy and Signal Engine | ✅ Roadmap step complete | Canonical five-state pipeline and primary signal ranking merged through PR #28 |
| 7 | Risk Engine Authority | 🟡 Partial | Core gates exist; frontend values are inconsistent and need one authoritative contract |
| 8 | Position sizing and exposure | ✅ Complete in code | SL-distance sizing, exchange constraints and portfolio exposure controls |
| 9 | Trade Execution Engine | ✅ Complete in code | Reservation, idempotency, fill confirmation and protection verification |
| 10 | Trade Management Engine | 🔴 Runtime defect | Partial TP fills worked; Scalping TP2 profit-lock failed in deployed verification |
| 11 | Journal and exact PnL sync | 🔴 Runtime defect | Partial closes, fees and realized PnL did not reconcile into the application |
| 12 | Frontend operations terminal | 🟡 Partial | UI truthfulness step merged; TP labels, settings consistency and blank-page stability remain |
| 13 | Deployment and observability | 🟡 Partial | Render deployment and Watchdog exist; deployed lifecycle verification remains incomplete |
| 14 | Full Bybit Demo E2E and soak testing | ⬜ Pending | Complete Scalping and Intraday entry-to-close evidence required |
| 15 | Live-release hardening | ⬜ Pending | Security, backups, monitoring, operations and approved demo evidence required |

---

## 6. Current Product Scope

DrayFrogd is designed to:

1. Scan liquid Bybit USDT perpetual markets.
2. Classify separate Scalping and Intraday trend contexts.
3. Rank eligible markets deterministically.
4. Evaluate enabled strategies only in the approved direction.
5. Produce canonical useful signals.
6. Recompute geometry and risk server-side.
7. Size positions using fixed USDT risk and SL distance.
8. Reserve risk, symbol and execution state before exchange submission.
9. Confirm actual fills and verify exchange protection.
10. Apply the authoritative Scalping or Intraday management profile.
11. Reconcile partial fills, fees, PnL and lifecycle evidence.
12. Provide an administrative React terminal for monitoring and control.

The application is **demo-first**. Live trading remains disabled until all release gates are completed and explicitly approved.

---

## 7. Architecture

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

---

## 8. Enabled Strategies

Current registered strategies:

1. **EMA Pullback**
2. **Breakout**
3. **Pure SMC**

Completed pipeline controls:

- Canonical five-state result contract.
- Direction enforcement through the full pipeline.
- Useful-signal retention and deduplication.
- One primary useful signal per symbol.
- Deterministic signal ranking.

Still required:

- Strategy version and enable/disable control.
- Historical backtesting and walk-forward validation.
- Failure analysis and controlled tuning workflow.
- Deployed runtime evidence linking each executed trade to its authoritative strategy metadata.

---

## 9. Locked Risk and Trade Profiles

Scalping and Intraday must never share one generic management profile.

| Rule | Scalping | Intraday |
|---|---:|---:|
| Fixed risk per trade | 20 USDT | 50 USDT |
| Maximum leverage | 20x | 10x |
| Minimum Risk:Reward | 1:1.5 | 1:2.0 |
| TP1 | 1.5R — close 50% | 2R — close 50% |
| TP2 | 2R — close 25% | 2.5R — close 25% |
| Final target / Runner | 2.5R — close final 25% | 3R — final 25% runner |
| Early protection | At 1R move SL to break-even + observed fee buffer | At TP1 move SL to break-even |
| After TP2 | Move remaining SL to TP1 price | Activate trailing protection |
| Trailing stop | Disabled | Enabled only after TP2 |
| Maximum duration | 59 minutes | 6 hours |

### Mandatory profile contract

Every managed trade must persist and enforce:

- `trade_type`
- `strategy_name`
- `management_profile`
- selected leverage
- TP1, TP2 and final/runner target
- TP allocation percentages
- break-even/profit-lock rule
- trailing enabled/disabled state
- maximum holding time
- authoritative exchange order IDs and quantities
- partial-fill, fee and realized-PnL evidence

An unknown or missing `trade_type` must not silently inherit a default profile. New management actions must be blocked until the trade profile is authoritative.

### Portfolio controls

- Maximum **5 active trades**.
- Same-symbol duplicate positions are blocked.
- Long/short geometry is recomputed by the backend.
- Total combined margin exposure cannot exceed **50% of account/day equity**.
- A realized losing close creates a **30-minute symbol cooldown**.
- Daily reset timezone is **Asia/Dhaka**.
- At **5% net realized daily loss**, new execution stops for that BDT day.
- Existing positions continue to be protected and reconciled.

Frontend cards and editable settings are not authoritative. They must render values returned from the backend risk contract.

---

## 10. Authoritative Execution Flow

```text
ACTIVE Signal
→ Fresh executable quote
→ Backend geometry and RR validation
→ Fixed-risk position sizing
→ Atomic risk / symbol / slot reservation
→ Exchange leverage configuration
→ Market order submission
→ Actual fill confirmation
→ Actual-fill risk and RR recheck
→ Install selected management profile
→ Attach and verify profile-specific final TP and initial SL
→ Install native TP1 / TP2 orders
→ Persist active-trade state and metadata
→ Reconcile partial fills, fees and PnL
```

Implemented safety controls include:

- Deterministic execution key and order-link ID.
- Duplicate execution prevention.
- Durable reservation before order submission.
- Actual fill and executed quantity persistence.
- Profile-specific protection installation.
- Emergency close when fill risk becomes unsafe.
- Emergency close when protection cannot be attached or verified.
- Uncertain exchange states are not reported as successful trades.

Runtime verification has shown that implementation claims must not be treated as complete until exchange-side behavior is confirmed.

---

## 11. Trade Management Rules

### Scalping profile

| Stage | Target | Quantity | Protection action |
|---|---:|---:|---|
| Early protection | 1R | No close | SL → break-even + observed fee buffer |
| TP1 | 1.5R | Close 50% | Keep protected stop |
| TP2 | 2R | Close 25% | Remaining 25% SL → TP1 price |
| Final TP | 2.5R | Close final 25% | Full exit; no trailing |

Additional Scalping rules:

- High-spread symbols are rejected using the repository's verified spread boundary.
- Trailing stop is disabled.
- Maximum trade duration is 59 minutes.
- The remaining 25% after TP2 must be protected at the TP1 price.

### Intraday profile

| Stage | Target | Quantity | Protection action |
|---|---:|---:|---|
| TP1 | 2R | Close 50% | SL → break-even |
| TP2 | 2.5R | Close 25% | Activate trailing protection |
| Runner | 3R target | Final 25% | Manage with approved trailing rule |

Additional Intraday rules:

- Maximum leverage is 10x.
- Trailing is enabled only after TP2.
- Maximum trade duration is 6 hours.

### Current runtime state

- Native partial TP orders can fill at the exchange.
- The observed Scalping TP2 protection amendment failed to move the remaining SL to TP1.
- Partial fills, fees and realized PnL were not fully reflected in the journal.
- Trade metadata recovery/adoption was not authoritative.

These findings override earlier code-only completion claims until repaired and re-tested.

---

## 12. Deferred and Critical Tasks

- Fix TP2 profit-lock amendment and exchange verification.
- Reconcile partial fills, entry/exit fees and realized PnL.
- Preserve strategy and management profile metadata across restart/deploy.
- Use authoritative exchange timestamps for lifecycle events.
- Classify bot, manual and external trades.
- Verify native order cancellation/cleanup on manual close, SL close and full close.
- Detect and clean orphan orders after crashes or exchange-side actions.
- Add private order/position WebSocket reconciliation.
- Add multi-instance worker ownership/locking before horizontal scaling.
- Complete partial-fill, amendment-rejection and latency tests.
- Protect or minimize public `/readiness` and `/exchange/status` operational details.
- Add session expiry and server-side logout/revocation hardening.
- Complete Settings and remove old project naming.
- Build historical data storage, backtesting and tuning.
- Complete Demo E2E, soak testing, backup and production operations review.

---

## 13. Remaining Roadmap — Recommended Order

### Phase A — Runtime Defect Repair

1. TP2 profit-lock fix.
2. Journal, fees and realized-PnL reconciliation.
3. Authoritative metadata recovery.
4. UI TP-stage and risk-value consistency.
5. Blank-page reproduction and repair.

### Phase B — Runtime Re-verification

1. Deploy the approved repair commit.
2. Verify database bootstrap, health and readiness.
3. Complete one full Scalping Bybit Demo lifecycle.
4. Complete one full Intraday Bybit Demo lifecycle.
5. Capture exchange, backend and journal evidence.
6. Verify restart and every close path.

### Phase C — Trade Management Hardening

1. Verify native TP cleanup on every close path.
2. Add orphan-order detection.
3. Add private exchange-stream reconciliation.
4. Add worker ownership locking.
5. Complete partial-fill and amendment tests.

### Phase D — Historical Data, Backtesting and Tuning

1. Build reusable historical OHLCV storage.
2. Support required 6-month, 1-year and 2-year datasets.
3. Run deterministic backtests using runtime-equivalent rules.
4. Add walk-forward and period-by-period evaluation.
5. Explain strategy failures and produce controlled tuning proposals.
6. Save comparable reports without duplicate data downloads.

### Phase E — Production Operations

1. Upgrade or migrate temporary database infrastructure.
2. Add scheduled backup and restore testing.
3. Add external monitoring and alert delivery.
4. Add API retry budgets and rate-limit handling.
5. Complete security, secrets and session review.
6. Define and approve the final live-release checklist.

---

## 14. Testing and Verification Rules

Automated checks must include:

- Backend compile check.
- Backend unit/integration suite.
- Frontend TypeScript check.
- Frontend production build.

A green automated suite proves only the tested code and build paths. It does **not** prove real exchange fills, latency, TP execution, protection amendments, journal synchronization or exchange-side state transitions.

Required release evidence:

- Exact changed files and diff.
- Targeted tests.
- Full available test suite.
- CI result.
- Deployed health/readiness.
- Bybit Demo order and position evidence for both profiles.
- TP1, TP2, protection amendment and final-close evidence.
- Journal, fees and realized-PnL evidence.
- Restart/recovery evidence.
- Orphan-order and close-path cleanup evidence.

---

## 15. Local Development

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

Local development database:

```text
sqlite:///./app.db
```

Keep `APP_ENV=development` when using SQLite.

---

## 16. Required Environment Variables

### Backend

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

### Frontend

- `VITE_API_BASE_URL`

Never commit API keys, passwords, session secrets, service-role credentials or `.env` files.

---

## 17. Safety and Release Rules

- Default mode is `demo`.
- Live mode is not production-approved.
- Scalping and Intraday management rules must remain separate.
- Unknown trade type must not receive a silent default management profile.
- Manual Run Scan must remain scan-only.
- Code completion is not runtime verification.
- Runtime verification is not live-capital approval.
- Do not describe a test as passed without evidence.
- Do not claim deployment or exchange behavior without deployed evidence.
- Use feature branches and pull requests for production changes.
- Do not merge to `main` without explicit Product Owner approval.
- Do not enable live trading before defect repair, both Demo lifecycles, soak testing, operations review and release approval.

---

## 18. Current Verdict

DrayFrogd has a substantial demo-trading application, completed Scanner/Signal roadmap and core safety architecture.

**Steps 1, 2 and 3 of the Scanner/Signal roadmap are complete and merged.**

The 12 July 2026 deployed verification proved real partial TP execution, but also confirmed a critical Scalping TP2 protection failure and incomplete journal/PnL reconciliation.

The project is not finished because Trade Management repair, authoritative reconciliation, complete Scalping and Intraday Demo lifecycles, restart/cleanup evidence, backtesting, operational hardening and live-release gates remain outstanding.

**Current classification: Demo Beta — runtime defects confirmed — live trading not approved.**

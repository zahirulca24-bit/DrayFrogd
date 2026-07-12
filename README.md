# DrayFrogd V2

Bybit-first automated trading terminal built with **FastAPI, React, PostgreSQL and Bybit V5 APIs**.

The project is currently in **Demo Beta / Engineering Verification**. Live-capital trading is not approved.

> **Overall roadmap completion:** 70%  
> **Current active roadmap:** Scanner → Strategy/Signal → UI Truthfulness  
> **Latest completed roadmap step:** Step 1 — Scanner Architecture  
> **Latest scanner merge:** PR #21 — `f30eda65b0ad06cf943ca952f5261a9807a2c477`  
> **Latest Scanner test evidence:** targeted 12/12, full backend 150/150  
> **Trade-management profiles:** Scalping and Intraday are separate  
> **Live trading:** blocked by default

---

## 1. Current 3-Step Roadmap

This is the active implementation roadmap. Completed items remain checked and each future completed step must be updated here with evidence.

### [x] Step 1 — Scanner Market Ranking, Trend Classification and Sideways Rejection

**Status:** Complete and merged through PR #21.

Implemented:

- Dynamic Bybit USDT perpetual candidate collection.
- Liquidity, turnover, movement and spread validation.
- Multi-timeframe analysis:
  - 1-hour trend context
  - 15-minute setup context
  - 5-minute trigger confirmation
- Open/current candles excluded from confirmed analysis.
- Deterministic trend states:
  - `UPTREND`
  - `DOWNTREND`
  - `SIDEWAYS`
  - `INSUFFICIENT_DATA`
- `UPTREND` permits Long setups only.
- `DOWNTREND` permits Short setups only.
- `SIDEWAYS`, stale and insufficient-data markets are blocked.
- Dynamic ranked universe of up to 50 eligible markets.
- Deterministic market score and score-component metadata.
- Existing Risk and Execution behavior remains unchanged.

Evidence:

- Targeted Scanner tests: **12/12 passed**.
- Full backend suite: **150/150 passed**.
- Merge commit: `f30eda65b0ad06cf943ca952f5261a9807a2c477`.

### [ ] Step 2 — Strategy and Signal Pipeline

**Status:** Pending.

Scope:

- Strategy Engine consumes only Scanner-ranked, trend-aligned markets.
- Approved strategies:
  - EMA Pullback
  - Breakout
  - Pure SMC
- Canonical result states:
  - `NO_SETUP`
  - `NEAR_SETUP`
  - `ACTIVE`
  - `INVALID`
  - `EXPIRED`
- Confirmed entries use closed candles only.
- Opposite-trend strategy results are rejected.
- Signal Engine keeps only useful results:
  - `NEAR_SETUP` → monitor only
  - `ACTIVE` → eligible for Risk and Execution gates
- `INVALID` and `EXPIRED` leave executable monitoring.
- One primary best-quality signal per symbol.
- Other valid strategy matches remain confirmation metadata.
- Signal ranking is deterministic using quality, confidence, freshness and valid risk geometry.
- Scanner, Risk, Position Sizing and Execution rules are outside this step.

Completion gates:

- Focused Strategy/Signal tests pass.
- Full backend suite passes.
- Exact changed files and diff are reviewed.
- Commit and merge require Product Owner approval.

### [ ] Step 3 — Scanner and Signal UI Truthfulness

**Status:** Pending.

Scanner UI must show:

- Symbols checked.
- Uptrend count.
- Downtrend count.
- Sideways rejected count.
- Insufficient/stale-data count.
- Ranked markets count.
- Strategy checks count.
- Near setups count.
- Active signals count.

Required presentation rules:

- A strategy-check total must not be shown as a symbol total.
- Market ranking and signal ranking must be separate layers.
- Strategy-valid state and account-executable state must be separate.
- No stale, placeholder or fabricated runtime values.

Signal cards must show:

- Market rank and market score.
- Trend state and approved direction.
- Strategy name and trade type.
- Entry, Stop Loss and Take Profit levels.
- Risk:Reward.
- Signal age.
- Near / Active / Expired state.
- Risk/Execution eligibility separately from strategy validity.

Completion gates:

- Backend contracts are stable first.
- Frontend TypeScript checks pass.
- Frontend production build passes.
- Screenshots are reviewed by the Product Owner.

---

## 2. Locked End-to-End Flow

```text
Bybit USDT Perpetual Market
→ Liquidity / Turnover / Movement / Spread Filter
→ Closed-Candle Multi-Timeframe Analysis
→ Trend Classification
→ Reject Sideways / Stale / Insufficient Markets
→ Rank Eligible Markets
→ Strategy Engine Evaluates Approved Strategies
→ Near Setup / Active Signal
→ Signal Engine Deduplicates and Ranks Useful Signals
→ Bot Monitors Signal Symbols Only
→ Active Signal + Risk Gate Passed
→ Trade Execution
→ Trade-Type-Specific Management Profile
→ Journal and PnL Reconciliation
```

Responsibility boundaries:

- **Scanner:** market filtering, trend classification and market ranking.
- **Strategy Engine:** setup detection and trade geometry proposals.
- **Signal Engine:** useful-result storage, deduplication and signal ranking.
- **Risk Engine:** final risk authority.
- **Execution Engine:** final exchange-order authority.
- **Trade Management:** profile-specific protection, TP stages, break-even, trailing and close lifecycle.

---

## 3. Project Progress

### Overall roadmap completion: **70%**

This score represents engineering milestone completion. It is not a profitability, safety or live-release claim.

| # | Milestone | Status | Current evidence / remaining gap |
|---|---|---|---|
| 1 | Repository foundation and CI | ✅ Complete | FastAPI, React, compile, backend tests, TypeScript check and frontend build |
| 2 | Authentication and bot controls | ✅ Complete | Admin login, session verification, start/stop, emergency stop, resume and demo/live gating |
| 3 | Database persistence and restart safety | ✅ Complete | SQLite local development, PostgreSQL deployment, journal and risk restoration |
| 4 | Bybit exchange integration | ✅ Complete in code | Wallet, positions, market data, order, leverage, protection and close APIs |
| 5 | Market Scanner | 🟡 Partial | Step 1 complete; Strategy/Signal pipeline and UI truthfulness remain |
| 6 | Strategy Engine | 🟡 Partial | EMA Pullback, Breakout and Pure SMC exist; Step 2 pipeline contract remains |
| 7 | Risk Engine Authority | ✅ Complete in code | Fixed-risk profiles, dynamic daily risk pool and circuit breaker |
| 8 | Position sizing and exposure | ✅ Complete in code | SL-distance sizing, exchange constraints and portfolio margin ceiling |
| 9 | Trade Execution Engine | ✅ Complete in code | Reservation, idempotency, fill confirmation and protection verification |
| 10 | Trade Management Engine | 🟡 Partial | Separate Scalping/Intraday profiles are implemented in code; real demo verification remains |
| 11 | Journal and exact PnL sync | ✅ Complete in code | Persistent journal, reconciliation and realized-PnL synchronization |
| 12 | Frontend operations terminal | 🟡 Partial | Main pages exist; Step 3 and Settings remain |
| 13 | Deployment and observability | 🟡 Partial | Render, health/readiness and Watchdog exist; latest runtime verification remains |
| 14 | Full Bybit Demo E2E and soak testing | ⬜ Pending | Entry-to-close multi-trade demo evidence required |
| 15 | Live-release hardening | ⬜ Pending | Security, backup, operations and approved demo evidence required |

---

## 4. Current Product Scope

DrayFrogd is designed to:

1. Scan liquid Bybit USDT perpetual markets.
2. Classify market trend and rank eligible symbols.
3. Evaluate enabled strategies only in the approved direction.
4. Build and rank useful trading signals.
5. Recompute trade geometry and risk server-side.
6. Size positions using fixed USDT risk and SL distance.
7. Reserve risk and execution state before exchange submission.
8. Confirm actual fills and verify exchange protection.
9. Apply the correct Scalping or Intraday management profile.
10. Persist trade, PnL, risk and operational evidence.
11. Provide an administrative React terminal for monitoring and control.

The application is **demo-first**. Live trading remains disabled until all release gates are completed and explicitly approved.

---

## 5. Architecture

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

## 6. Enabled Strategies

Current registered strategies:

1. **EMA Pullback**
2. **Breakout**
3. **Pure SMC**

Strategy completion still requires:

- Canonical five-state result contract.
- Direction enforcement through the full pipeline.
- Useful-signal retention and deduplication.
- One primary signal per symbol.
- Deterministic signal ranking.
- Strategy version and enable/disable control.
- Historical backtesting and walk-forward validation.
- Failure analysis and controlled tuning workflow.

---

## 7. Locked Risk and Trade Profiles

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

---

## 8. Authoritative Execution Flow

```text
Active Signal
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
→ Persist active-trade state
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

---

## 9. Trade Management Rules

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
- The remaining 25% after TP2 is protected at the TP1 price.

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

### Implemented behavior

- TP1 and TP2 use exchange-native GTC reduce-only limit orders.
- Native order IDs, quantities, targets and statuses are persisted.
- The dedicated watcher reconciles native order state every 2 seconds.
- The profile-specific final TP is installed and exchange-verified.
- Scalping 1R protection is checked by the dedicated watcher.
- Scalping TP2 applies a TP1-price profit lock to the final 25%.
- Intraday TP1 moves the remaining position SL to break-even.
- Intraday TP2 activates trailing protection.
- Protection updates are verified against the exchange position.
- Position-size reconciliation remains available as a restart-safe fallback.
- Eligible existing full-size active trades can be adopted after restart/deploy.
- Cancelled, rejected or deactivated native orders switch to the mark-price fallback.
- Native-order mode blocks duplicate polling-based partial closes.
- Maximum-hold and stagnant-trade exits remain fallback management rules.

### Trade Management work still required

- Real Bybit Demo verification of both Scalping and Intraday TP lifecycles.
- Native order cancellation/cleanup verification on manual close, SL close and full position close.
- Orphan-order detection and cleanup after crashes or exchange-side manual actions.
- Private order/position WebSocket integration; current watcher uses periodic REST reconciliation.
- Multi-instance worker ownership/locking before horizontal scaling.
- Extended tests for partial fills, order amendments, rejected amendments and exchange latency.

---

## 10. Deferred Critical Tasks

These remain separate bounded tasks after Steps 2 and 3:

- Journal restart reconciliation and authoritative exchange timestamps.
- Entry fees, realized PnL and daily net-PnL verification.
- Strategy and trade-type persistence after restart verification.
- Bot/manual/external trade classification.
- Scalping 20x and Intraday 10x runtime verification.
- Scalping and Intraday TP-ladder runtime verification.
- Failed or uncertain reservation cleanup.
- Authentication expiry and server-side logout hardening.
- Settings completion.
- Historical data storage, backtesting and tuning.
- Deployment, demo E2E and soak testing.

---

## 11. Remaining Roadmap — Recommended Order

### Phase A — Finish the Active 3-Step Roadmap

1. ✅ Step 1 — Scanner Architecture.
2. ⬜ Step 2 — Strategy and Signal Pipeline.
3. ⬜ Step 3 — Scanner and Signal UI Truthfulness.

### Phase B — Runtime Verification

1. Deploy the approved latest `main`.
2. Verify database bootstrap, health and readiness.
3. Complete full Scalping and Intraday Bybit Demo lifecycles.
4. Capture backend, journal and exchange evidence.
5. Fix only evidence-confirmed runtime defects.

### Phase C — Trade Management Hardening

1. Verify TP cleanup on every close path.
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

### Phase E — UI and Operator Experience

1. Align all frontend risk values with backend authority.
2. Show risk pool, live downside risk and breaker reasons.
3. Show selected trade profile, native TP status and protection state.
4. Complete Settings.
5. Remove old project naming.
6. Add deployment and runtime-verification panels.

### Phase F — Production Operations

1. Upgrade or migrate temporary database infrastructure.
2. Add scheduled backup and restore testing.
3. Add external monitoring and alert delivery.
4. Add API retry budgets and rate-limit handling.
5. Complete security and secrets review.
6. Define the final live-release checklist.

---

## 12. Testing and Verification Rules

Automated checks must include:

- Backend compile check.
- Backend unit/integration suite.
- Frontend TypeScript check.
- Frontend production build.

A green automated suite proves only the tested code and build paths. It does **not** prove real exchange fills, latency, TP execution or exchange-side state transitions.

Required release evidence:

- Exact changed files and diff.
- Targeted tests.
- Full available test suite.
- CI result.
- Deployed health/readiness.
- Bybit Demo order and position evidence for both profiles.
- Journal and PnL evidence.
- Restart/recovery evidence.

---

## 13. Local Development

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

## 14. Required Environment Variables

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

## 15. Safety and Release Rules

- Default mode is `demo`.
- Live mode is not production-approved.
- Scalping and Intraday management rules must remain separate.
- Unknown trade type must not receive a silent default management profile.
- Code completion is not runtime verification.
- Runtime verification is not live-capital approval.
- Do not describe a test as passed without evidence.
- Do not claim a deployment without deployment evidence.
- Use feature branches and pull requests for production changes.
- Do not merge to `main` without explicit Product Owner approval.
- Do not enable live trading before demo E2E, soak testing, operations review and release approval.

---

## 16. Current Verdict

DrayFrogd has a substantial demo-trading application and core safety architecture.

**Step 1 of the current Scanner roadmap is complete. Steps 2 and 3 remain pending.**

**Scalping and Intraday now have separately documented management profiles.** Runtime enforcement exists in code through PR #20, but both profiles still require full Bybit Demo lifecycle verification.

The project is not finished because Strategy/Signal pipeline completion, truthful Scanner/Signal UI, real Bybit Demo E2E verification, backtesting, operational hardening and live-release gates remain outstanding.

**Current classification: Demo Beta — 70% roadmap complete, runtime verification required, live trading not approved.**

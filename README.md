# DrayFrogd V2

Bybit-first automated trading terminal built with **FastAPI, React, PostgreSQL and Bybit V5 APIs**.

The project is currently in **Demo Beta / Engineering Verification**. Live-capital trading is not approved.

> **Active roadmap:** 2 of 3 steps complete  
> **Latest completed step:** Strategy and Signal Pipeline  
> **Latest merge:** PR #28 — `c216a9af96e87a3d466ca0f1a70e3c4825650444`  
> **Latest CI evidence:** backend **180/180 passed**, frontend TypeScript and production build passed  
> **Next bounded task:** Scanner and Signal UI Truthfulness  
> **Live trading:** blocked by default

---

## 1. Current Verified Status

Three backend workstreams are complete in code and merged:

1. ✅ **Trade Management Profiles**
2. ✅ **Scanner Correction and Profile Separation**
3. ✅ **Strategy and Signal Pipeline**

Runtime exchange verification is still required before any live-release decision.

### Latest verified merges

| Workstream | Pull request | Merge commit | CI evidence |
|---|---:|---|---|
| Separate Scalping and Intraday Trade Management | #20 | `30ddd4b6aaa076cdb447ac4acd9496d788ee3c53` | profile and execution-management tests passed |
| Scanner profile separation and Top-30 ranking | #27 | `1e2d31690616553cf1c93d669d132188d783a9c8` | backend **171/171**, frontend checks passed |
| Canonical Strategy and Signal Pipeline | #28 | `c216a9af96e87a3d466ca0f1a70e3c4825650444` | backend **180/180**, frontend checks passed |

---

## 2. Active 3-Step Roadmap

### [x] Step 1 — Scanner Market Ranking and Profile Separation

**Status:** Complete and merged through PR #27.

Implemented:

- Dynamic Bybit USDT perpetual candidate collection.
- Liquidity, turnover, movement and spread validation.
- Dynamic ranked universe capped at **Top 30** eligible markets.
- Explicit `market_rank` from 1 to 30.
- Open/current candles excluded from confirmed analysis.
- Separate profile pipelines:
  - **Scalping:** 5-minute trend/setup → 1-minute trigger.
  - **Intraday:** 1-hour trend → 15-minute setup → 5-minute trigger.
- Deterministic trend states:
  - `UPTREND`
  - `DOWNTREND`
  - `SIDEWAYS`
  - `INSUFFICIENT_DATA`
  - stale-data rejection
- `UPTREND` permits Long setups only.
- `DOWNTREND` permits Short setups only.
- Sideways, stale and insufficient-data profiles are blocked before strategy evaluation.
- Scanner and Strategy/Signal responsibilities are separated.
- Missing or unknown `trade_type` cannot silently default to Scalping.

Evidence:

- Merge commit: `1e2d31690616553cf1c93d669d132188d783a9c8`.
- Backend suite: **171/171 passed**.
- Frontend TypeScript check: passed.
- Frontend production build: passed.

### [x] Step 2 — Strategy and Signal Pipeline

**Status:** Complete and merged through PR #28.

Implemented:

- Strategy Engine consumes only eligible Scanner-ranked contexts.
- Registered strategies:
  - EMA Pullback
  - Breakout
  - Pure SMC
- Canonical signal states:
  - `NO_SETUP`
  - `NEAR_SETUP`
  - `ACTIVE`
  - `INVALID`
  - `EXPIRED`
- `NEAR_SETUP` is monitor-only.
- Only valid `ACTIVE` signals are execution-eligible before Risk and Execution gates.
- Opposite-trend results are invalidated.
- Missing `trade_type` is invalidated.
- Invalid Long/Short entry, Stop Loss and Take Profit geometry is blocked.
- Scalping and Intraday contexts are evaluated separately.
- One deterministic primary useful signal is retained per symbol.
- Same-direction strategy/profile matches are retained as confirmation metadata.
- Opposite-direction useful matches are retained as alternates, not duplicate primary signals.
- Signal score, signal rank, signal key and state counts are exposed.

Evidence:

- Merge commit: `c216a9af96e87a3d466ca0f1a70e3c4825650444`.
- Backend suite: **180/180 passed**.
- Frontend TypeScript check: passed.
- Frontend production build: passed.

### [ ] Step 3 — Scanner and Signal UI Truthfulness

**Status:** Pending — this is the next bounded task.

Scanner UI must show real backend values for:

- Symbols checked.
- Uptrend count.
- Downtrend count.
- Sideways rejection count.
- Insufficient/stale-data count.
- Ranked-market count.
- Strategy-check count.
- Near-setup count.
- Active-signal count.

Required presentation rules:

- A strategy-check total must not be displayed as a symbol total.
- Market ranking and signal ranking must remain separate.
- Strategy validity and account execution eligibility must remain separate.
- No stale, placeholder or fabricated runtime values.
- Empty states and unavailable values must be reported honestly.

Signal cards must show:

- Market rank and market score.
- Signal rank and signal score.
- Trend state and approved direction.
- Strategy name and trade type.
- Entry, Stop Loss and Take Profit.
- Risk:Reward.
- Signal age.
- Canonical signal state.
- Monitor-only or execution-eligible state.
- Risk and execution eligibility separately from strategy validity.

Completion gates:

- Backend contracts remain unchanged unless a proven UI requirement needs a bounded contract update.
- Frontend TypeScript check passes.
- Frontend production build passes.
- UI screenshots are reviewed by the Product Owner.
- No merge to `main` without Product Owner approval.

---

## 3. Locked End-to-End Flow

```text
Bybit USDT Perpetual Market
→ Liquidity / Turnover / Movement / Spread Filter
→ Closed-Candle Profile Analysis
→ Reject Sideways / Stale / Insufficient Profiles
→ Rank Top 30 Eligible Markets
→ Build Separate Scalping and Intraday Contexts
→ Strategy Engine Evaluates Registered Strategies
→ Canonical Signal-State Normalization
→ Validate Trend, Trade Type and Trade Geometry
→ Select One Primary Useful Signal per Symbol
→ NEAR_SETUP Monitoring or ACTIVE Risk Gate
→ Position Sizing and Execution Authority
→ Trade-Type-Specific Management Profile
→ Journal and PnL Reconciliation
```

Responsibility boundaries:

- **Scanner:** market filtering, profile eligibility, trend classification and market ranking.
- **Strategy Engine:** setup detection and trade-geometry proposals.
- **Signal Pipeline:** canonical states, validation, deduplication and signal ranking.
- **Risk Engine:** final risk authority.
- **Position Sizing:** exchange-compliant quantity authority.
- **Execution Engine:** final exchange-order authority.
- **Trade Management:** profile-specific protection, TP stages, break-even, trailing and close lifecycle.

---

## 4. Current Product Scope

DrayFrogd is designed to:

1. Scan liquid Bybit USDT perpetual markets.
2. Rank a maximum of 30 eligible markets.
3. Evaluate Scalping and Intraday contexts separately.
4. Evaluate registered strategies only in the approved direction.
5. Normalize strategy results into the canonical signal contract.
6. Keep one primary useful signal per symbol.
7. Recompute trade geometry and risk server-side.
8. Size positions using fixed USDT risk and Stop Loss distance.
9. Reserve risk and execution state before exchange submission.
10. Confirm actual fills and verify exchange protection.
11. Apply the correct Scalping or Intraday management profile.
12. Persist trade, PnL, risk and operational evidence.
13. Provide an administrative React terminal for monitoring and control.

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
        +-- Signal Pipeline
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

## 6. Registered Strategies and Signal Contract

Current registered strategies:

1. **EMA Pullback**
2. **Breakout**
3. **Pure SMC**

Canonical signal contract:

| State | Meaning | Execution behavior |
|---|---|---|
| `NO_SETUP` | No valid setup exists | Do not monitor or execute |
| `NEAR_SETUP` | Valid developing setup | Monitor only |
| `ACTIVE` | Confirmed valid signal | May proceed to Risk and Execution gates |
| `INVALID` | Contract, trend, trade type or geometry failed | Block |
| `EXPIRED` | Signal validity window ended | Remove from executable monitoring |

Completed pipeline behavior:

- Direction enforcement.
- Mandatory explicit `trade_type`.
- Trade-geometry validation.
- Useful-signal retention.
- One primary signal per symbol.
- Confirmation and alternate-match metadata.
- Deterministic signal ranking.

Future strategy work remains separate:

- Strategy versioning and operator enable/disable controls.
- Historical data storage.
- Deterministic backtesting.
- Walk-forward validation.
- Failure analysis and controlled tuning.

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
- break-even or profit-lock rule
- trailing enabled/disabled state
- maximum holding time

An unknown or missing `trade_type` must not inherit a default profile. New management actions remain blocked until the profile is authoritative.

### Portfolio controls

- Maximum **5 active trades**.
- Same-symbol duplicate positions are blocked.
- Long/Short geometry is recomputed by the backend.
- Total combined margin exposure cannot exceed **50% of account/day equity**.
- A realized losing close creates a **30-minute symbol cooldown**.
- Daily reset timezone is **Asia/Dhaka**.
- At **5% net realized daily loss**, new execution stops for that BDT day.
- Existing positions continue to be protected and reconciled.

---

## 8. Authoritative Execution Flow

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

### Runtime verification still required

- Real Bybit Demo verification of both profile lifecycles.
- Break-even, TP1, TP2, final target and trailing behavior.
- Native-order cancellation and cleanup on every close path.
- Orphan-order detection after crashes or exchange-side manual actions.
- Restart and deployment recovery evidence.
- Partial-fill, amendment, rejection and exchange-latency tests.

---

## 10. Remaining Roadmap — Recommended Order

### Phase A — Finish the Active Roadmap

1. ✅ Scanner Market Ranking and Profile Separation.
2. ✅ Strategy and Signal Pipeline.
3. ⬜ Scanner and Signal UI Truthfulness.

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
4. Add worker-ownership locking.
5. Complete partial-fill and amendment tests.

### Phase D — Historical Data, Backtesting and Tuning

1. Build reusable historical OHLCV storage.
2. Support required 6-month, 1-year and 2-year datasets.
3. Run deterministic backtests using runtime-equivalent rules.
4. Add walk-forward and period-by-period evaluation.
5. Explain strategy failures and produce controlled tuning proposals.
6. Save comparable reports without duplicate data downloads.

### Phase E — UI and Operator Experience

1. Complete Scanner and Signal UI Truthfulness.
2. Align frontend risk values with backend authority.
3. Show risk pool, live downside risk and circuit-breaker reasons.
4. Show selected trade profile, native TP status and protection state.
5. Complete Settings.
6. Add deployment and runtime-verification panels.

### Phase F — Production Operations

1. Upgrade or migrate temporary database infrastructure.
2. Add scheduled backup and restore testing.
3. Add external monitoring and alert delivery.
4. Add API retry budgets and rate-limit handling.
5. Complete security and secrets review.
6. Define the final live-release checklist.

---

## 11. Testing and Verification Rules

Automated checks must include:

- Backend compile check.
- Backend unit and integration suite.
- Frontend TypeScript check.
- Frontend production build.

A green automated suite proves only tested code and build paths. It does **not** prove real exchange fills, latency, TP execution or exchange-side state transitions.

Required release evidence:

- Exact changed files and diff.
- Targeted tests.
- Full available test suite.
- CI result.
- Deployed health and readiness.
- Bybit Demo order and position evidence for both profiles.
- Journal and PnL evidence.
- Restart and recovery evidence.

---

## 12. Local Development

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

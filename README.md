# DrayFrogd V2

Bybit-first automated trading terminal built with **FastAPI, React, PostgreSQL and Bybit V5 APIs**.

The project is currently in **Demo Beta / Engineering Verification**. Live-capital trading is not approved.

> **Overall roadmap completion:** 70%  
> **Current active roadmap:** Scanner → Strategy/Signal → UI Truthfulness  
> **Latest completed roadmap step:** Step 1 — Scanner Architecture  
> **Latest scanner merge:** PR #21 — `f30eda65b0ad06cf943ca952f5261a9807a2c477`  
> **Latest Trade Management merge:** PR #20 — `30ddd4b6aaa076cdb447ac4acd9496d788ee3c53`  
> **Live trading:** blocked by default

## Today’s Runtime Verification Checklist — 12 July 2026

Checked items have repository, deployment or exchange-screen evidence. Unchecked items still require real Bybit Demo runtime evidence.

### Completed and evidenced today

- [x] PR #20 merged into `main`.
- [x] Render backend deployed merge commit `30ddd4b6aaa076cdb447ac4acd9496d788ee3c53` and reported **Deploy live**.
- [x] A fresh TUUSDT Demo position opened after deployment.
- [x] Scalping TP1 was placed at approximately **1.5R** for **50%** quantity: `0.005685`, quantity `68,800`.
- [x] Scalping TP2 was placed at approximately **2R** for **25%** quantity: `0.005757`, quantity `34,400`.
- [x] Scalping final TP was placed at approximately **2.5R** for the remaining **25%**: `0.005828`.
- [x] Initial SL was present at `0.005328` for entry near `0.005471`.
- [x] Scalping and Intraday Trade Management profiles are separated in code and passed CI.
- [x] Scanner and execution spread gates use the approved **50 bps** maximum and passed CI.

### Runtime verification still pending

- [ ] At approximately **1R (`0.005614`)**, TUUSDT SL moves to entry/break-even plus the available observed-fee buffer.
- [ ] TP1 closes the expected 50% quantity and records partial realized PnL.
- [ ] TP2 closes another 25% quantity.
- [ ] After TP2, the remaining Scalping SL moves to the TP1 price near `0.005685`.
- [ ] Scalping uses **no trailing stop** after TP2.
- [ ] Final 25% closes at 2.5R and exact exit, PnL and fees synchronize into the Journal.
- [ ] Any remaining Scalping quantity closes automatically at the **59-minute** maximum hold time.
- [ ] A verified coin above the 50 bps spread limit is rejected before order submission.
- [ ] A fresh Intraday trade uses the separate **2R / 2.5R / 3R** ladder, trailing protection and **6-hour** maximum hold time.
- [ ] Backend restart or redeploy restores active trade and native TP state without duplicate orders.
- [ ] Manual close, SL close and full TP close clean up all remaining native orders.

---

## 1. Current 3-Step Roadmap

### [x] Step 1 — Scanner Architecture

**Status:** Complete and merged through PR #21.

Implemented:

- Dynamic Bybit USDT perpetual candidate collection.
- Liquidity, turnover, movement and spread validation.
- Closed-candle multi-timeframe analysis using 1h, 15m and 5m context.
- Deterministic `UPTREND`, `DOWNTREND`, `SIDEWAYS` and `INSUFFICIENT_DATA` states.
- Long-only permission in uptrends and short-only permission in downtrends.
- Sideways, stale and insufficient markets are blocked.
- Dynamic ranked universe of up to 50 eligible markets.
- Market score and timeframe evidence are included in scanner output.

Evidence:

- Targeted Scanner tests: **12/12 passed**.
- Full backend suite at merge: **150/150 passed**.
- Merge commit: `f30eda65b0ad06cf943ca952f5261a9807a2c477`.

### [ ] Step 2 — Strategy and Signal Pipeline

Pending scope:

- Strategy Engine consumes only Scanner-ranked, trend-aligned markets.
- Approved strategies remain EMA Pullback, Breakout and Pure SMC.
- Canonical states: `NO_SETUP`, `NEAR_SETUP`, `ACTIVE`, `INVALID`, `EXPIRED`.
- Confirmed entries use closed candles only.
- Opposite-trend results are rejected.
- One primary best-quality signal per symbol.
- Other valid strategy matches remain confirmation metadata.
- Useful signals are deterministically ranked by quality, confidence, freshness and risk geometry.

### [ ] Step 3 — Scanner and Signal UI Truthfulness

Pending UI requirements:

- Show symbols checked, trend counts, sideways rejections, stale/insufficient counts and ranked-market count.
- Keep market ranking separate from signal ranking.
- Keep strategy validity separate from account execution eligibility.
- Show market rank, market score, trend, direction, strategy, trade type, entry, SL, TP, RR and signal age.
- Show no stale, placeholder or fabricated runtime values.

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
→ Active Signal + Risk Gate Passed
→ Trade Execution
→ Trade Management
→ Journal and PnL Reconciliation
```

Responsibility boundaries:

- **Scanner:** market filtering, trend classification and market ranking.
- **Strategy Engine:** setup detection and trade geometry proposals.
- **Signal Engine:** useful-result storage, deduplication and signal ranking.
- **Risk Engine:** final risk authority.
- **Execution Engine:** final exchange-order authority.
- **Trade Management:** protection, TP stages, break-even, trailing and close lifecycle.

---

## 3. Project Progress

| # | Milestone | Status | Current evidence / remaining gap |
|---|---|---|---|
| 1 | Repository foundation and CI | ✅ Complete | FastAPI, React, compile, backend tests, TypeScript and frontend build |
| 2 | Authentication and bot controls | ✅ Complete | Login, session verification, start/stop, emergency stop and demo/live gating |
| 3 | Database persistence and restart safety | ✅ Complete | SQLite local, PostgreSQL deployment, journal and risk restoration |
| 4 | Bybit integration | ✅ Complete in code | Wallet, positions, market data, order, leverage, protection and close APIs |
| 5 | Market Scanner | 🟡 Partial | Step 1 complete; Strategy/Signal pipeline and UI truthfulness remain |
| 6 | Strategy Engine | 🟡 Partial | Three strategies exist; Step 2 pipeline contract remains |
| 7 | Risk Engine Authority | ✅ Complete in code | Fixed-risk profiles, dynamic risk pool and circuit breaker |
| 8 | Position sizing and exposure | ✅ Complete in code | SL-distance sizing, exchange constraints and portfolio margin ceiling |
| 9 | Trade Execution Engine | ✅ Complete in code | Reservation, idempotency, fill confirmation and protection verification |
| 10 | Trade Management Engine | 🟡 Partial | New profile ladder is deployed; full runtime lifecycle remains unverified |
| 11 | Journal and exact PnL sync | ✅ Complete in code | Persistent journal, reconciliation and realized-PnL synchronization |
| 12 | Frontend operations terminal | 🟡 Partial | Main pages exist; truthful Step 3 UI and Settings remain |
| 13 | Deployment and observability | 🟡 Partial | Render, health/readiness and Watchdog exist; soak verification remains |
| 14 | Full Bybit Demo E2E | ⬜ Pending | Entry-to-close multi-trade evidence required |
| 15 | Live-release hardening | ⬜ Pending | Security, backup, operations and approved demo evidence required |

---

## 4. Locked Risk and Portfolio Policy

| Rule | Scalping | Intraday |
|---|---:|---:|
| Fixed risk per trade | 20 USDT | 50 USDT |
| Maximum leverage | 20x | 10x |
| Minimum Risk:Reward | 1:1.5 | 1:2.0 |
| Maximum duration | 59 minutes | 6 hours |
| Trailing stop | Disabled | Enabled after TP2 |

Portfolio controls:

- Maximum **5 active trades**.
- Same-symbol duplicates are blocked.
- Total combined margin exposure cannot exceed **50% of account/day equity**.
- A realized losing close creates a **30-minute symbol cooldown**.
- Daily reset timezone is **Asia/Dhaka**.
- At **5% net realized daily loss**, new execution stops for that BDT day.
- Existing positions continue to be protected and reconciled.

---

## 5. Trade Management Profiles

### Scalping

- 1R: SL moves to break-even plus available observed-fee buffer.
- 1.5R: TP1 closes 50%.
- 2R: TP2 closes 25%.
- 2.5R: final 25% closes.
- After TP2, remaining SL moves to the TP1 level.
- No trailing stop.
- Maximum hold time: 59 minutes.

### Intraday

- 2R: TP1 closes 50% and SL moves to break-even.
- 2.5R: TP2 closes 25% and trailing protection begins.
- 3R: final runner target for remaining 25%.
- Maximum hold time: 6 hours.

Common implementation:

- Native reduce-only TP orders.
- Exchange protection verification.
- Position and order reconciliation after restart.
- Manual-close and degraded fallback paths.
- 50 bps spread check at scanner and execution boundaries.

Still required:

- Complete the unchecked runtime checklist above.
- Add orphan-order cleanup.
- Add private exchange-stream reconciliation.
- Add multi-instance worker ownership locking.
- Complete partial-fill and order-amendment tests.

---

## 6. Remaining Roadmap

1. Finish Strategy and Signal Pipeline.
2. Finish truthful Scanner and Signal UI.
3. Complete the full Bybit Demo runtime checklist.
4. Harden TP cleanup, orphan detection and restart behavior.
5. Build reusable historical OHLCV storage.
6. Add deterministic backtesting, walk-forward evaluation and controlled tuning.
7. Complete Settings, monitoring, backup/restore and security review.
8. Run multi-trade Demo soak testing before any live-release decision.

---

## 7. Testing and Release Rules

Automated checks include backend compile/tests, frontend TypeScript and production build.

A green suite proves only tested code and build paths. It does **not** prove real exchange fills, latency, TP execution or exchange-side transitions.

Required release evidence:

- Exact changed files and diff.
- Targeted and full tests.
- CI result.
- Deployed health/readiness.
- Bybit Demo order and position evidence.
- Journal, PnL and fee evidence.
- Restart and recovery evidence.

Safety rules:

- Default mode is `demo`.
- Live mode is not production-approved.
- Code completion is not runtime verification.
- Runtime verification is not live-capital approval.
- Never claim a test or deployment without evidence.
- Use feature branches and pull requests.
- Do not merge to `main` without explicit Product Owner approval.

---

## 8. Local Development

Backend:

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m app.database_bootstrap
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Local database defaults to `sqlite:///./app.db`. Keep `APP_ENV=development` when using SQLite.

---

## 9. Current Verdict

DrayFrogd has a substantial demo-trading application and core safety architecture.

**Scanner Step 1 and the separate Scalping/Intraday Trade Management code are complete. Runtime verification remains incomplete.**

The project is not finished because Strategy/Signal pipeline completion, truthful UI, full Bybit Demo E2E verification, backtesting, operational hardening and live-release gates remain outstanding.

**Current classification: Demo Beta — 70% roadmap complete, runtime verification required, live trading not approved.**

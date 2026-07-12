# DrayFrogd V2

Bybit-first automated trading terminal built with **FastAPI, React, PostgreSQL and Bybit V5 APIs**. The project currently targets **demo trading and controlled engineering verification**. Live-capital trading is not approved.

> **Current release stage:** Demo Beta / Engineering Verification  
> **Latest verified engine merge:** PR #17 — merge commit `977ec927399d999d1cb8739c4749bff4f3a1a427`  
> **Latest verified engine CI:** Run #167 — backend and frontend passed  
> **Live trading status:** Blocked by default and not production-approved

---

## 1. Project Progress

### Overall roadmap completion: **70%**

This is a transparent milestone score, not a claim that the bot is 70% profitable or 70% safe for live money.

Calculation:

```text
15 total milestones
8 Complete  = 8.0
5 Partial   = 2.5   (0.5 each)
2 Pending   = 0.0
------------------
10.5 / 15 = 70%
```

| # | Milestone | Status | Current evidence / remaining gap |
|---|---|---|---|
| 1 | Repository foundation and CI | ✅ Complete | FastAPI, React, Python/Node CI, compile, tests, TypeScript check and frontend build |
| 2 | Authentication and bot controls | ✅ Complete | Admin login, session verification, start/stop, emergency stop, resume, demo/live gating |
| 3 | Database persistence and restart safety | ✅ Complete | SQLite for local development, PostgreSQL for deployment, journal and risk-state restoration |
| 4 | Bybit exchange integration | ✅ Complete in code | Wallet, positions, market data, orders, leverage, SL/TP and close APIs are integrated; latest runtime flow still needs demo verification |
| 5 | Market scanner and market-data workflow | 🟡 Partial | Dynamic 30-symbol USDT universe, 5m setup and 1m trigger data exist; Top-20 → Best-10 ranking and streaming data are not complete |
| 6 | Strategy Engine | 🟡 Partial | EMA Pullback, Breakout and Pure SMC exist; Hybrid strategy, explicit intraday strategies, backtesting and tuning are pending |
| 7 | Risk Engine Authority | ✅ Complete in code | Fixed-USDT profiles, dynamic risk pool, 5% daily net-loss breaker, 30m loss cooldown, 5 active-trade limit |
| 8 | Position sizing and portfolio exposure | ✅ Complete in code | SL-distance sizing, precision/min-notional validation, 20x/10x profiles and 50% combined margin ceiling |
| 9 | Trade Execution Engine | ✅ Complete in code | Atomic reservation, idempotency, live quote, actual fill confirmation, fill-risk recheck and protection verification |
| 10 | Trade Management Engine | 🟡 Partial | Native TP1/TP2, break-even and trailing are implemented and unit-tested; real Bybit Demo verification and lifecycle hardening remain |
| 11 | Journal, reconciliation and exact PnL sync | ✅ Complete in code | Persistent journal, exact close sync, partial realized-PnL sync, restart reconciliation and cooldown restoration |
| 12 | Frontend operations terminal | 🟡 Partial | Dashboard, Signal Engine, Active Trades, Journal, Performance, Control Panel and Watchdog exist; Settings and Signal redesign remain incomplete |
| 13 | Deployment and observability | 🟡 Partial | Render Blueprint, PostgreSQL, health/readiness and Watchdog exist; latest `main` deployment and production operations are not verified |
| 14 | Full Bybit Demo E2E and soak testing | ⬜ Pending | New code must be tested through entry → native TP fills → BE → trailing → exact close/PnL over multiple trades |
| 15 | Live release hardening | ⬜ Pending | Security review, backup/restore, operational limits, release gates and approved demo-performance evidence are required |

---

## 2. Current Product Scope

DrayFrogd is designed to:

1. Scan liquid Bybit USDT perpetual markets.
2. Build 5-minute setup context and 1-minute entry triggers.
3. Evaluate enabled strategies.
4. Recompute trade geometry and risk server-side.
5. Size the position from fixed USDT risk and SL distance.
6. Reserve portfolio risk and execution state before sending an order.
7. Confirm the actual exchange fill and verify SL/TP protection.
8. Manage profit-taking, break-even, trailing protection and final close reconciliation.
9. Persist trade, PnL, risk and operational evidence.
10. Provide an administrative React dashboard for monitoring and control.

The project is **demo-first**. Live trading must remain disabled until the remaining release gates are completed and explicitly approved.

---

## 3. Architecture

```text
React + TypeScript Frontend
        |
        | authenticated REST API
        v
FastAPI Backend
        |
        +-- Scanner and Strategy Engine
        +-- Dynamic Risk Engine
        +-- Position Sizing
        +-- Authoritative Execution Service
        +-- Native TP / Trade Management
        +-- Journal and Reconciliation
        +-- Watchdog and Bot Controls
        |
        +-- PostgreSQL (deployment)
        +-- SQLite (local development)
        |
        v
Bybit V5 Demo / Live APIs
```

### Technology stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy |
| Frontend | React, TypeScript, Vite |
| Exchange | Bybit V5 REST APIs |
| Production database | PostgreSQL |
| Local database | SQLite |
| Hosting configuration | Render Blueprint |
| CI | GitHub Actions |

---

## 4. Implemented Frontend Pages

| Page | Current capability | Status |
|---|---|---|
| Dashboard | Readiness, account, signals, active trades and one-click start control | ✅ Implemented |
| Signal Engine | Scanner results, signal review and manual demo execution | 🟡 Existing; redesign PR is not merged |
| Active Trades | Live positions, management state and manual controls | ✅ Implemented |
| Journal / Trade History | Persistent trade records and close evidence | ✅ Implemented |
| Performance & Strategy | Strategy and trading-performance summaries | ✅ Implemented baseline |
| Control Panel | Start/stop, emergency control, mode, risk and system telemetry | ✅ Implemented |
| Watchdog | Module state, incidents and bot events | ✅ Implemented |
| Settings | Placeholder only | ⬜ Pending |

### Frontend technical debt

- The offline/default risk-state values in the frontend still reflect older limits and must be aligned with the current Risk Engine contract.
- The browser title still contains an older project name and requires naming cleanup.
- Native TP order status, dynamic risk-pool values and exact risk-capacity explanations should be exposed clearly in the UI.
- PR #11 (`fix/signal-engine-user-friendly-layout`) is still a draft and is no longer mergeable against the current `main`; it must be rebased, rebuilt or replaced rather than merged as-is.

---

## 5. Scanner and Strategy Engine

### Implemented scanner behavior

- Dynamic universe of up to 30 Bybit USDT perpetual symbols.
- Turnover and 24-hour price-movement filters.
- 5-minute candles for setup/bias context.
- 1-minute candles for entry triggers.
- Active, near-setup, blocked, rejected and expired result states.
- Manual scan remains diagnostic; automatic trading is controlled globally.

### Enabled strategies

1. **EMA Pullback**
2. **Breakout**
3. **Pure SMC**

All currently registered strategies use the 5m setup / 1m trigger workflow and are currently classified as **scalping** unless a future strategy explicitly emits `trade_type="intraday"`.

### Strategy work still required

- Hybrid Liquidity Sweep + Displacement + FVG Retest strategy.
- Explicit intraday strategies using the intraday risk profile.
- Top-20 scanner → Best-10 executable-signal ranking.
- A+/A grading contract and deterministic ranking rules.
- Duplicate/near-duplicate signal suppression across scan cycles.
- Historical backtesting and walk-forward validation.
- Failure analysis and parameter-tuning workflow.
- Strategy enable/disable and version tracking from the Control Panel.

---

## 6. Locked Risk Engine Policy

### Trade profiles

| Rule | Scalping | Intraday |
|---|---:|---:|
| Fixed risk per trade | 20 USDT | 50 USDT |
| Maximum profile leverage | 20x | 10x |
| Minimum Risk:Reward | 1:1.5 | 1:2.0 |

### Portfolio rules

- Maximum **5 active trades**.
- No daily executable-trade count limit.
- Same-symbol duplicate position is blocked.
- Long/short geometry is recomputed by the backend.
- Submitted RR is compared with authoritative RR.
- Total combined margin exposure cannot exceed **50% of day/account equity**.
- A realized losing close starts a **30-minute symbol cooldown**.
- Daily reset timezone is **Asia/Dhaka**.

### Dynamic daily risk pool

```text
Base Risk Pool      = BDT day-start equity × 5%
Effective Risk Pool = Base Risk Pool + today's net realized PnL
Available Risk      = Effective Risk Pool − current live downside risk
```

Behavior:

- Profit increases available risk capacity.
- Realized loss reduces available capacity.
- Moving SL to entry/break-even reduces that trade's live downside risk to zero.
- A profitable protective stop also contributes zero downside risk.
- At **5% net realized daily loss**, the circuit breaker stops new execution for that BDT day.
- Existing positions must continue to be reconciled and protected even when new execution is blocked.

---

## 7. Position Sizing and Margin Policy

```text
Quantity = Fixed USDT Risk / Absolute SL Distance
Notional = Quantity × Entry Price
Required Margin = Notional / Selected Profile Leverage
```

The sizing engine validates:

- Fresh equity and available balance.
- SL distance.
- Exchange quantity step and price tick.
- Minimum order quantity and minimum notional.
- Actual risk after quantity normalization.
- Existing authoritative exchange-position margin.
- Combined 50% portfolio margin ceiling.

The 50% exposure cap is a **maximum portfolio ceiling**, not a target for one trade. Fixed-risk scalping uses the approved 20x profile and intraday uses 10x, provided the trade fits available balance and portfolio capacity.

---

## 8. Authoritative Execution Flow

```text
Signal
  → Live executable quote
  → Backend RR and geometry validation
  → Fixed-risk position sizing
  → Atomic risk + symbol + active-slot + execution reservation
  → Exchange leverage configuration
  → Market order submission
  → Order recovery by deterministic orderLinkId if response is ambiguous
  → Actual fill / average entry confirmation
  → Actual fill risk and RR recheck
  → Initial SL/TP attachment and exchange verification
  → Native TP1/TP2 order installation
  → Active trade persistence
```

### Execution safety already implemented

- Deterministic execution key and `orderLinkId`.
- Durable reservation before exchange submission.
- Duplicate execution prevention.
- Atomic portfolio-risk reservation.
- Actual average fill and executed quantity persistence.
- Actual fill risk/RR validation.
- Emergency close if the confirmed fill becomes unsafe.
- Emergency close if initial protection cannot be attached or verified.
- Uncertain order/fill states are not reported as successful active trades.
- Exact close and PnL remain pending until exchange evidence is synchronized.

---

## 9. Trade Management Rules

### Profit distribution

| Stage | Target | Quantity |
|---|---:|---:|
| TP1 | 2R | 50% |
| TP2 | 2.5R | 25% |
| Runner | 3R | 25% |

### Implemented behavior

- TP1 and TP2 use exchange-native GTC reduce-only limit orders.
- Native order IDs, quantities, targets and statuses are persisted.
- A dedicated watcher reconciles native order state every 2 seconds.
- TP1 fill moves the remaining position SL to actual average entry/break-even.
- TP2 fill activates runner trailing protection.
- Protection updates are verified against the exchange position.
- Position-size reconciliation is available as a restart-safe fallback.
- Eligible existing full-size active trades can be adopted after restart/deploy.
- Cancelled/rejected/deactivated native orders switch to the legacy mark-price fallback.
- Native-order mode blocks duplicate polling-based partial closes.
- Maximum hold and stagnant-trade exits exist as fallback management rules.

### Trade Management work still required

- Real Bybit Demo verification of TP1, BE, TP2 and trailing behavior.
- Native order cancellation/cleanup verification on manual close, SL close and full position close.
- Orphan order detection and cleanup after crashes or exchange-side manual actions.
- WebSocket/private order stream integration; current native fill watcher uses periodic REST reconciliation.
- Multi-instance worker ownership/locking before horizontal scaling.
- Extended tests for partial fills, order amendments, rejected amendments and exchange latency.

---

## 10. Persistence, Journal and Reconciliation

Implemented:

- Persistent trade journal.
- Strategy name and execution metadata persistence.
- Order ID, execution key, actual fill and protection evidence.
- Active/closed trade reconstruction after restart.
- Exact close fill and net realized PnL synchronization.
- Partial realized-PnL synchronization while a runner remains open.
- Loss-cooldown reconstruction from authoritative negative realized PnL.
- BDT day-start equity and circuit-breaker persistence.
- Bot-event and Watchdog incident history.

Known database work:

- Replace runtime schema-alter helpers with a formal migration workflow such as Alembic.
- Define managed PostgreSQL backup and restore procedures.
- Migrate any required historical SQLite records manually before retiring an old SQLite deployment.

---

## 11. Testing Status

### Automated CI

GitHub Actions currently runs:

- Python 3.12 dependency installation.
- Backend compile check.
- Backend `unittest` suite.
- Node.js 22 dependency installation.
- Frontend TypeScript/lint check.
- Frontend production build.
- Test log artifacts.

The latest verified engine change, PR #17, passed the backend and frontend jobs in CI run #167.

### Important limitation

Automated tests use mocks/fakes for exchange behavior. A green CI result proves the tested code paths and build pass; it does **not** prove real Bybit Demo order behavior, fills, latency, TP execution or exchange-side state transitions.

---

## 12. Immediate Next Verification Gate

Do not call the latest engine release fully verified until the following is completed on the deployed Bybit Demo environment.

### New trade verification checklist

- [ ] Latest `main` commit is deployed.
- [ ] Backend health and readiness are green.
- [ ] New scalping trade uses approximately 20 USDT SL risk.
- [ ] Scalping leverage is 20x and margin does not consume the full 50% portfolio budget.
- [ ] Actual fill price and executed quantity appear in the journal.
- [ ] Initial SL and runner protection are visible on Bybit.
- [ ] TP1 2R reduce-only order exists for 50% quantity.
- [ ] TP2 2.5R reduce-only order exists for 25% quantity.
- [ ] TP1 fill books profit on Bybit.
- [ ] Remaining SL moves to actual entry/break-even after TP1.
- [ ] TP2 fill reduces another 25% and starts trailing protection.
- [ ] Remaining runner quantity is correct.
- [ ] Partial realized PnL is synchronized into daily risk capacity.
- [ ] Final close records exact realized PnL and fees.
- [ ] A losing close creates a 30-minute symbol cooldown.
- [ ] Restart/deploy restores active trade and native TP state without duplicate orders.

### Soak test required

After the single-trade gate passes, run a multi-trade demo soak test covering:

- Long and short trades.
- Multiple symbols.
- Consecutive wins and losses.
- TP1-only then BE exit.
- TP1 + TP2 + runner exit.
- SL exit.
- Manual close.
- Backend restart with an active position.
- Network/API interruption.
- Daily BDT reset and 5% circuit breaker.

---

## 13. Remaining Roadmap — Recommended Order

### Phase A — Deploy and Runtime Verification

1. Deploy latest `main` to Render.
2. Verify database bootstrap and readiness.
3. Complete the Bybit Demo checklist above.
4. Capture screenshots, journal evidence and Bybit order evidence.
5. Fix only evidence-confirmed runtime defects.

### Phase B — Trade Management Hardening

1. Verify native TP cleanup on every close path.
2. Add orphan-order detection.
3. Add private order/position WebSocket reconciliation.
4. Add worker ownership lock for multi-instance safety.
5. Complete partial-fill and amendment tests.

### Phase C — Scanner and Strategy Completion

1. Lock Top-20 scan and Best-10 executable ranking rules.
2. Add A+/A grading.
3. Build the Hybrid Liquidity Sweep + FVG strategy.
4. Add explicit intraday strategies and trade-type classification.
5. Rebuild or replace stale Signal Engine PR #11.
6. Expose strategy versions and enable/disable control.

### Phase D — Historical Data, Backtesting and Tuning

1. Build reusable historical OHLCV storage.
2. Support 6-month, 1-year and 2-year test datasets where required.
3. Implement deterministic backtests using the same strategy/risk rules as runtime.
4. Add walk-forward and period-by-period evaluation.
5. Explain why a strategy failed and produce controlled tuning proposals.
6. Save comparable result reports without repeatedly downloading identical data.

### Phase E — UI and Operator Experience

1. Align all frontend risk types and fallback values with the current backend.
2. Show risk pool, live risk, available risk and breaker reasons.
3. Show native TP1/TP2 order IDs, status, fill quantity and BE/trailing state.
4. Complete Settings.
5. Clean old project naming.
6. Add clear runtime-verification and deployment status panels.

### Phase F — Production Operations

1. Upgrade or migrate the limited-lifetime free PostgreSQL database.
2. Add scheduled backup and restore testing.
3. Add external monitoring and alert delivery.
4. Add rate-limit handling, API retry budgets and operational dashboards.
5. Complete security and secrets review.
6. Define an approved live-release checklist based on verified demo evidence.

---

## 14. Known Limitations and Non-Claims

- Real Bybit Demo E2E behavior of the latest execution and native TP changes is not yet verified.
- The scanner currently returns up to 30 liquid symbols; the planned Top-20 → Best-10 final ranking is not complete.
- The Hybrid strategy is not in the active Strategy Engine registry.
- The intraday risk profile exists, but current registered strategies default to scalping.
- There is no completed historical backtesting/tuning engine in this repository.
- Native TP fills are reconciled by a 2-second REST watcher, not a private WebSocket stream.
- Settings is a placeholder.
- Signal Engine redesign PR #11 must not be merged as-is.
- Render's free PostgreSQL plan has a limited lifetime and is not permanent production storage.
- Existing SQLite records are not migrated automatically.
- The project is not approved for unattended live-capital trading.

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

Local development defaults to:

```text
sqlite:///./app.db
```

Keep `APP_ENV=development` when using SQLite.

---

## 16. Required Secrets and Environment Variables

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

Never commit real API keys, session secrets or service-role credentials.

---

## 17. Render Deployment

`render.yaml` defines:

- `drayfrogd-backend` — Python web service.
- `drayfrogd-frontend` — static React site.
- `drayfrogd-db` — managed PostgreSQL database.
- Backend database bootstrap before Uvicorn startup.
- `/health` health check.
- Production SQLite rejection through `APP_ENV=production`.

### Deployment sequence

1. Merge an approved PR into `main`.
2. Confirm the merge commit and CI evidence.
3. Sync or deploy the Render services from the repository.
4. Supply every environment variable marked `sync: false`.
5. Set `VITE_API_BASE_URL` to the deployed backend URL.
6. Confirm startup log contains `Database bootstrap complete`.
7. Confirm `/health` and readiness responses.
8. Confirm the frontend can authenticate and read the backend.
9. Run the Bybit Demo runtime checklist.
10. Restart the backend and verify journal/risk/native-order state restoration.

### Render free PostgreSQL limitation

The current Blueprint requests Render's free PostgreSQL plan. It persists across normal backend redeploys, but it has a limited lifetime and is unsuitable for permanent production retention. Upgrade it or migrate the data before expiration.

---

## 18. Safety and Release Rules

- Default execution mode is `demo`.
- Live mode remains unavailable until live Bybit keys are present and an administrator changes the mode.
- Code completion and CI success do not equal runtime verification.
- Runtime verification does not equal live-capital approval.
- Do not merge feature branches without explicit approval.
- Do not describe a test as passed without evidence.
- Do not claim a Render deployment occurred without deployment evidence.
- Do not enable live trading until the demo soak test, operations review and release checklist are explicitly approved.

---

## 19. Recent Critical Merges

| PR | Change | Status |
|---:|---|---|
| #12 | Journal redesign | Merged |
| #13 | Control Panel and Watchdog | Merged |
| #14 | Dynamic Risk Engine authority | Merged |
| #15 | Authoritative execution and fill verification | Merged |
| #16 | Margin efficiency and 50% portfolio exposure correction | Merged |
| #17 | Exchange-native TP1/TP2 and reliable break-even management | Merged |

---

## 20. Current Verdict

DrayFrogd now has a substantial **demo trading application and core safety architecture**. The Risk Engine, position sizing, authoritative execution, persistent journal and native profit-management code are implemented and covered by automated tests.

The project is **not finished** because the latest engine stack has not completed real Bybit Demo E2E verification, the strategy/scanner roadmap is incomplete, backtesting is absent, operational hardening is incomplete and live-release gates have not been approved.

**Current classification: Demo Beta — 70% roadmap complete, runtime verification required, live trading not approved.**

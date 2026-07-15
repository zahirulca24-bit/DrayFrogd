# DayForge V2

> **DayForge — Forge Better Trading Every Day**

Bybit-first automated trading terminal built with **FastAPI, React, PostgreSQL and Bybit V5 APIs**.

The project is in **Demo Beta / Engineering Verification**. Live-capital trading is not approved.

> **Last documentation update:** 16 July 2026 (`Asia/Dhaka`)  
> **Latest `main` commit:** `1d28a6ea` — canonical Backtest/live-pipeline parity merged  
> **Current engineering phase:** canonical Scalping/Intraday engine separation and Backtest parity are merged  
> **Automated verification:** GitHub Actions run #572 **PASS**; backend compile/tests **PASS**; frontend TypeScript/build **PASS**  
> **Runtime status:** **CODE PASS / RUNTIME PENDING** — fresh Render and Bybit Demo verification is still required  
> **Runtime tracker:** Issue #37  
> **Live trading:** blocked by default

> **Current audit update:** 16 July 2026 (`Asia/Dhaka`)  
> **Latest observed `main` commit:** `1d28a6ea` — PR #75 merged  
> **Engine status:** Scalping and Intraday are separate canonical profiles/engines that share approved strategy, signal-normalization and execution infrastructure  
> **Merge chain:** PR #71, #72, #73, #74 and #75 are merged after fresh CI verification  
> **Runtime proof:** Scanner/Backtest profile metadata and private Demo execution lifecycle remain **PENDING**

> **Risk sizing update:** `FEE-RISK-001` is merged in `bead839`. Position sizing keeps strategy SL/TP fixed and reduces quantity using Stop Loss distance plus estimated open/close fees, so a normal SL hit is sized against net loss instead of price movement only.

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
8. Size positions using fixed USDT risk, Stop Loss distance and estimated open/close fees.
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
        +-- Canonical Scalping Engine Profile
        +-- Canonical Intraday Engine Profile
        +-- Shared Approved Strategy Layer
        +-- Canonical Signal Engine / Signal Gate
        +-- Risk Engine
        +-- Position Sizing
        +-- Execution Service
        +-- Trade-Type-Specific Management
        +-- Backtest Engine using canonical profile/signal gates
        +-- Journal and Authoritative Reconciliation
        +-- Bybit Private/Public WebSocket Service
        +-- Browser WebSocket Status Polling
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
| Exchange | Bybit V5 REST + private/public WebSocket APIs |
| Production database | PostgreSQL |
| Local database | SQLite |
| Hosting | Render |
| CI | GitHub Actions |

## 3. Locked end-to-end flow

```text
Bybit USDT Perpetual Market
→ Liquidity / Turnover / Movement / Spread Filter
→ Closed-Candle Profile-Specific Analysis
→ Scalping Engine or Intraday Engine Context
→ Trend Classification
→ Reject Sideways / Stale / Insufficient Markets
→ Rank Eligible Markets
→ Shared Approved Strategy Layer
→ Canonical Signal State and Signal Gate
→ Signal Engine Deduplication and Ranking
→ ACTIVE Signal
→ Risk Gate
→ Position Sizing and Atomic Reservation
→ Exchange Execution
→ Trade-Type-Specific Management
→ Exchange-authoritative Position Reconciliation
→ Private/Public WebSocket Event Ingestion
→ Journal Lifecycle and Exact Fees/Realized PnL
→ One Authoritative Operator Snapshot
```

## 4. Scanner and Signal rules

- Ranked universe uses the memory-safe configured limit; current production default is **Top 12**.
- **Scalping:** 15-minute trend + 5-minute setup + 1-minute trigger.
- **Intraday:** 1-hour trend + 15-minute setup + 5-minute trigger.
- Scalping and Intraday use separate canonical engine profiles and risk contracts.
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

Breakout and Pure SMC consume setup and trigger timeframes separately. Setup timeframe supplies structural context; trigger timeframe supplies confirmation/invalidation evidence.

## 6. Locked Risk and Trade profiles

Scalping and Intraday must never share one generic management profile.

| Rule | Scalping | Intraday |
|---|---:|---:|
| Timeframes | 15m trend / 5m setup / 1m trigger | 1h trend / 15m setup / 5m trigger |
| Fixed risk per trade | 20 USDT | 50 USDT |
| Maximum leverage | 20x | 10x |
| Minimum Risk:Reward | 1:1.5 | 1:2.0 |
| TP1 | 1.5R — close 50% | 2R — close 50% |
| TP2 | 2R — close 25% | 2.5R — close 25% |
| Final target / Runner | 2.5R — final 25% | 3R — final 25% runner |
| Early protection | At 1R move SL to break-even plus observed fee buffer | At TP1 move SL to break-even |
| After TP2 | Move remaining SL to TP1 price | Activate trailing protection |
| Trailing stop | Disabled | Enabled only after TP2 |
| Backtest maximum hold | 30 trigger candles | 72 trigger candles |
| Maximum live duration | 59 minutes | 6 hours |

Every managed trade must persist authoritative `trade_type`, `strategy_name`, `engine_profile`, `management_profile`, leverage, TP ladder, allocation, protection rule and lifecycle timestamps.

An unknown or conflicting profile must fail closed and must not silently inherit Scalping or Intraday management.

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
| 3 | Recover authoritative strategy/profile metadata | Canonical `trade_type`/`engine_profile` architecture merged; deployed verification pending |
| 4 | Correct TP labels and Risk/daily-trade UI values | Pending |
| 5 | Blank-page stability | Signal page browser verification **PASS** |
| 6 | Complete Scalping Demo re-verification | Pending |
| 7 | Complete Intraday Demo re-verification | In progress |
| 8A | `STATE-SYNC-001` authoritative exchange position reconciliation | **Merged in PR #39 — runtime verification in progress** |
| 8B | `WS-001` Bybit private/public streams and browser connection status | **Runtime FAIL — both channels displayed reconnecting** |
| 8B.1 | `WS-RUNTIME-001` independent channel supervision and exact errors | **Merged in PR #41 — runtime pending** |
| 8C | Restart, close cleanup and orphan-order verification | Pending deployed verification |
| 9 | ACTIVE-signal execution decision visibility | Audit complete; implementation pending after state-sync runtime check |
| 10 | Historical data/backtesting parity | **Merged in PR #75 — code/CI PASS, runtime pending** |
| 11 | Canonical dual-engine architecture | **PR #71–#74 merged — code/CI PASS, runtime pending** |

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
- **After fresh ZIP audit:** `STATE-SYNC-001 + WS-001` was implemented on `fix/authoritative-state-bybit-websocket`.
- **PR #39:** Backend **205/205 PASS**, frontend TypeScript/build **PASS**, and GitHub Actions run #296 **PASS**.
- **2:50 AM BDT:** Product Owner approved and PR #39 merged into `main` at commit `94a6282ecac582b5f7e5e206f16f3e7861b0ae4b`.
- **2:57 AM BDT:** Deployed Dashboard showed `PRIVATE WS · RECONNECTING` and `PUBLIC WS · RECONNECTING` while REST account/state values remained available.
- **After runtime evidence:** Product Owner approved `WS-RUNTIME-001` hotfix.
- **CI run #305:** Backend failed because the new test module imported `pytest`, while repository CI uses the standard-library `unittest` runner; no product-code failure was indicated.
- **CI run #307:** Tests were converted to native `unittest`; backend **203/203 PASS**, frontend TypeScript/build **PASS**.
- **CI run #309:** Final README-synchronized branch head passed backend and frontend jobs.
- **3:18 AM BDT:** Product Owner approved and PR #41 merged into `main` at commit `718aa343d9531770bc3a5f05c18b62715bcf189c`.

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
| Active Trades realized PnL | **PASS** | `$27.6431` displayed |
| Account equity/available balance refresh | **PASS** | Dashboard refreshed after close |
| Signal Engine browser stability | **PASS** | Page loads and displays ranked markets/signals |
| Journal exact exit price | **PENDING EVIDENCE** | Final Journal screenshot still required |
| Journal exact fees | **PENDING EVIDENCE** | Final Journal screenshot still required |
| TP1 moved SL to break-even | **PENDING EVIDENCE** | Bybit protection screenshot required at TP1 |
| TP2 started trailing protection | **PENDING EVIDENCE** | Bybit protection screenshot required at TP2 |
| Restart recovery | **PENDING** | Not yet tested |
| Native order cleanup/orphan check | **PENDING** | Not yet tested |

### Accounting verdict

The deployed PR #36 build proves that the realized-PnL accounting path functions after the LABUSDT trade closed:

- Dashboard realized PnL updated from `$0.00` to `$27.64`.
- Active Trades realized PnL displayed `$27.6431`.
- Dashboard net PnL matched realized PnL after unrealized PnL returned to zero.

**Result:** Realized-PnL synchronization is **RUNTIME PASS**.

This does not prove the TP1 break-even or TP2 trailing protection transitions. Those remain open in Issue #37.

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
| Canonical Scalping/Intraday engine separation | **100% code** | PR #71–#73 merged; runtime profile-selection proof pending |
| Breakout/Pure SMC multi-timeframe correctness | **100% code** | PR #74 merged; runtime strategy evidence pending |
| Backtest/live signal-generation parity | **100% code** | PR #75 merged; real market-data runtime pending |
| ACTIVE-signal execution-capacity audit | **0%** | New bounded audit item |
| Restart/cleanup/orphan-order verification | **0%** | Not started |

### `STATE-SYNC-001 + WS-001` bounded implementation

The refresh mismatch was traced to conflicting active-trade authorities: exchange positions, Journal rows, process memory and read endpoints could independently rebuild or mutate state. The implementation establishes one exchange-authoritative operator snapshot and adds real-time Bybit event ingestion without treating WebSocket delivery as a substitute for REST reconciliation.

#### Implemented behavior

- Bybit open positions are the active-position authority.
- Journal data is retained as lifecycle/metadata evidence; a Journal-only stale row is not counted as an active exchange position.
- Position matching uses execution mode, symbol, direction and position index, with legacy fallback only when unambiguous.
- Exchange-only positions are recovered deterministically and are not duplicated by repeated refresh/restart cycles.
- `/active-trades` is read-only and no longer mutates global active state during a page refresh.
- Metrics, Portfolio, Dashboard and Active Trades consume the same authoritative snapshot.
- A failed REST refresh preserves the previous snapshot as stale instead of making positions disappear.
- Risk and reservation capacity count only capacity-blocking execution states.
- Private Bybit WebSocket topics cover positions, orders, executions and wallet events.
- Public Bybit WebSocket topics cover active/ranked-symbol ticker updates and top-of-book updates for active positions.
- Private WebSocket events trigger debounced REST reconciliation and are backed by the normal periodic REST truth checks.
- The browser polls an authenticated WebSocket-status endpoint and shows private/public connection state in a persistent badge.

#### Automated evidence

| Check | Result |
|---|---|
| Full backend suite | **205/205 PASS** |
| New authoritative-reconciliation tests | **PASS** |
| Exchange-only recovery and idempotency | **PASS TEST** |
| Journal-only stale row excluded from active snapshot | **PASS TEST** |
| Exact Bybit close synchronization precedes stale classification | **PASS TEST** |
| Opposite-side same-symbol identity separation | **PASS TEST** |
| Transient REST failure preserves prior snapshot | **PASS TEST** |
| Private execution-event reconciliation trigger | **PASS TEST** |
| Public ticker patch test | **PASS TEST** |
| Python compile | **PASS** |
| Frontend TypeScript check | **PASS** |
| Frontend production build | **PASS** |
| GitHub Actions run #296 | **PASS** |
| Product Owner merge approval | **PASS** |
| Merge to `main` | **PASS — `94a6282ecac582b5f7e5e206f16f3e7861b0ae4b`** |

#### Runtime gates still required

- Render deployment completes with the official `pybit` SDK dependency.
- Private WS authenticates through the official `pybit` SDK in Bybit Demo and receives position/order/execution/wallet events.
- Public WS receives ticker/order-book events and reconnects cleanly.
- Exchange, Dashboard, Active Trades and Journal agree after repeated browser refreshes.
- Backend restart recovers each exchange position exactly once with preserved metadata where available.
- Exchange 0 positions + stale Journal row produces 0 active trades and explicit attention state.
- Partial fill, fees, realized PnL and TP lifecycle remain correct after WS/REST reconciliation.
- Disconnect/reconnect and REST fallback do not duplicate trades or erase the last valid snapshot.

### `WS-RUNTIME-001` runtime defect and hotfix scope

The first deployed WebSocket check showed both badges as `RECONNECTING`. The original service used one shared supervisor: any exception marked both channels reconnecting and closed both clients. It also marked the private stream connected immediately after construction instead of waiting for pybit's confirmed authentication flag.

The approved hotfix establishes these rules:

- Private and public streams run in independent supervisor tasks and independent exponential backoff loops.
- A private failure cannot change or close the public channel; a public failure cannot change or close the private channel.
- `CONNECTED` requires the underlying pybit `is_connected()` check.
- Private `CONNECTED` additionally requires pybit's successful `auth` state.
- Status exposes endpoint, connect attempts, reconnect count, health-check time, next retry and exact exception text.
- The browser visibly displays exact private/public errors instead of hiding them only in a tooltip.
- WebSocket-triggered reconciliation remains separate and REST remains the accounting/state authority.

### Current verdict

PR #41 is merged into `main`. `WS-RUNTIME-001` code and CI are **PASS**, but the corrected build has not yet been verified on Render or against live Bybit Demo WebSocket endpoints. No WebSocket runtime PASS is claimed. `STATE-SYNC-001` remains under deployed verification, and REST reconciliation remains the active accounting/state authority.

### `JOURNAL-LEDGER-SYNC-002` repo audit after Bybit transaction-log screenshots

The latest deployed screenshots showed that Bybit Demo transaction history already contains exact trade ledger evidence: direction, quantity, filled price, fee paid, cash flow, change and wallet balance. The application still displayed incomplete Journal rows, zero Performance PnL, incomplete SL-hit analysis and low-price Dashboard cards rounded to `$0.00`.

This audit was performed against repository `main` at commit `e6099e8`. The code repair has since been merged, but no fresh Bybit Demo/Render runtime PASS is claimed.

#### Confirmed repo root causes

| Area | Repository evidence | Runtime symptom |
|---|---|---|
| Missing Bybit ledger ingestion | `app/exchange.py` lacked a `/v5/account/transaction-log` fetcher | Bybit Transaction Log had exact rows, but Journal/Performance could not consume them |
| Close sync depended on closed-PnL only | `app/close_fill_sync.py` relied on `/v5/position/closed-pnl` | Closed rows could remain without exact exit, fee or realized PnL |
| Pending close was persisted as closed | Missing exact close evidence could still produce a terminal-looking row | Journal showed `CLOSED` with `N/A` financial values |
| Win/loss classification mismatch | Metrics accepted a narrower result vocabulary than reconciliation emitted | Win rate, PnL-R and SL-hit metrics could stay wrong |
| Performance fabricated zero PnL for unknown closes | Null realized PnL was mapped to zero | Performance showed `$0.00` when the result was unknown |
| Tiny-price formatting was too coarse | Fixed two-decimal money formatting | Low-price instruments displayed as `$0.00` |
| Protection no-op logged as error | All protection exceptions were treated as failures | Incident Center could show noisy `not modified` errors |

#### Verification gate

`JOURNAL-LEDGER-SYNC-002` must not be called runtime-fixed until a fresh Bybit Demo lifecycle proves:

- a new open trade creates a Journal record;
- partial and final close rows are repaired from Bybit transaction-log evidence;
- fees, cash flow/change, exit price and realized PnL persist across refresh and restart;
- Dashboard, Active Trades, Journal, Performance and Bybit agree for the same symbols;
- unknown rows remain `N/A` or `SYNC PENDING`, never fake `$0.00`;
- backend tests, frontend TypeScript and frontend production build pass.

---

## 16 July 2026 — Thursday

### Canonical dual-engine and Backtest parity merge chain

| PR | Scope | Fresh CI | Merge result |
|---:|---|---|---|
| #71 | Canonical Scalping and Intraday engine profiles/adapters | Previous CI evidence verified | **Merged — `740ffa4e`** |
| #72 | Canonical Risk and Trade Management profile authority | Conflict repaired and verified | **Merged — `af657dec`** |
| #73 | Scanner canonical profile wiring with memory-safe limits preserved | Run #566 **PASS** | **Merged — `c173ad5d`** |
| #74 | Breakout and Pure SMC setup/trigger timeframe correctness | Run #569 **PASS** | **Merged — `b8732d25`** |
| #75 | Backtest defaults and canonical live signal-gate parity | Run #572 **PASS** | **Merged — `1d28a6ea`** |

### Architecture verdict

Scalping and Intraday are **separate canonical engines/profiles**, not one generic mode with shared numerical rules.

```text
Scanner
  ├─ Scalping Engine: 15m trend → 5m setup → 1m trigger
  └─ Intraday Engine: 1h trend → 15m setup → 5m trigger
            ↓
Shared approved strategy layer
            ↓
Canonical signal normalization and validation
            ↓
Risk / Execution / Trade-Type-Specific Management / Backtest
```

Shared infrastructure is intentional. It avoids duplicate strategy, normalization and execution code while keeping timeframe, risk, minimum R:R, leverage and management contracts independent.

### Current verification status

| Gate | Status |
|---|---|
| Canonical profile source of truth | **CODE PASS** |
| Scanner memory-safe limits preserved | **CI PASS** |
| Scalping minimum 1.5R | **CODE/TEST PASS** |
| Intraday minimum 2.0R and raw 1.5R adjustment | **CODE/TEST PASS** |
| Breakout/Pure SMC multi-timeframe behavior | **CODE/TEST PASS** |
| Backtest canonical defaults and signal gates | **CODE/TEST PASS** |
| Render deployment of latest `main` | **PENDING** |
| Live Scanner `trade_type`/`engine_profile` evidence | **PENDING** |
| Real Bybit market Backtest execution | **PENDING** |
| Private Bybit Demo order/protection lifecycle | **PENDING** |

**Overall verdict:** `CODE PASS / RUNTIME PENDING`. Live-capital approval remains blocked.

### Next tasks

1. Confirm Render deploys merge commit `1d28a6ea2622935d3beba67bceebd7315fd7a4bb`.
2. Verify separate Scalping and Intraday rows expose matching `trade_type`, `engine_profile`, timeframes and risk contract.
3. Confirm Intraday ACTIVE signals cannot remain below `2.0R`.
4. Run canonical Scalping and Intraday Backtests against reachable Bybit market data.
5. Verify private Demo execution/protection lifecycle separately before any production-release decision.

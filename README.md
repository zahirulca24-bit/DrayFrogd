# DrayFrogd V2

FastAPI + React automated futures trading platform for Bybit Demo Trading, with persistent PostgreSQL journaling, restart-safe risk state, authoritative order execution, exchange-native partial profit taking, and structured trade-management controls.

> **Current verified main baseline:** `977ec927399d999d1cb8739c4749bff4f3a1a427`  
> **Documentation updated:** 12 July 2026  
> **Execution mode:** Demo by default. Live mode remains locked unless valid live credentials are configured and an administrator explicitly enables it.

---

## Current engine status

| Engine / Module | Status | Notes |
|---|---:|---|
| Risk Engine Authority | Implemented | Persistent BDT-day risk state, fixed-USDT risk profiles, dynamic risk capacity, circuit breaker and symbol cooldown |
| Position Sizing | Implemented | Quantity from SL distance and fixed USDT risk; exchange precision and minimum notional enforced |
| Margin Efficiency | Implemented | Profile leverage is used; 50% exposure is a portfolio ceiling, not a one-trade target |
| Trade Execution Engine | Implemented | Single authoritative execution path, atomic reservation, fill verification and protection verification |
| Native TP / Break-even | Implemented | Exchange-native TP1 and TP2, 2-second reconciliation, BE and trailing updates |
| Persistent Journal | Implemented | PostgreSQL-backed open/closed trade history, events, execution metadata and exact close sync |
| Restart Recovery | Implemented | Risk state, active trades and native TP state are reconstructed from persistent/exchange evidence |
| Real Bybit Demo E2E verification | **Pending** | A fresh deployed trade must still prove the complete sequence on the real Demo account |

**Important:** Passing CI proves the code and test suite are consistent. It does not replace a real Bybit Demo runtime verification.

---

## Trading terminology

### Open trades today
The number of trades that were successfully opened on the exchange during the current BDT day. A trade remains part of the daily opened-trade history after it closes.

### Active trades
Trades that are currently open on the exchange and still have remaining position quantity.

The engine uses an **active trade limit**, not a daily opened-trade limit.

---

## Locked Risk Engine policy

### Global controls

- Maximum active trades: **5**
- Maximum daily executable trade count: **Unlimited**
- Same symbol duplicate position: **Blocked**
- Opposite position on an already-active symbol: **Blocked**
- Loss cooldown: **30 minutes for the affected symbol**
- Cooldown trigger: authoritative negative realized PnL
- Total portfolio margin exposure: **Maximum 50% of account equity**
- Daily reset timezone: **Asia/Dhaka (BDT)**

### Daily engine-stop rule

The only daily loss stop is:

```text
Daily Net Realized Loss Limit = 5% of BDT day-start equity
```

Example:

```text
BDT day-start equity: 1,000 USDT
Maximum daily net realized loss: 50 USDT
```

When the limit is reached:

- the bot stops accepting new trades;
- existing positions remain under protection and management;
- the circuit breaker remains persisted across restarts;
- the daily financial state resets at BDT midnight.

### Trade profiles

| Profile | Fixed risk per trade | Minimum RR | Maximum leverage |
|---|---:|---:|---:|
| Scalping | 20 USDT | 1:1.5 | 20x |
| Intraday | 50 USDT | 1:2 | 10x |

Leverage is a profile cap and margin-efficiency control. It does not define the trade risk. The actual downside risk is calculated from:

```text
Position Quantity = Fixed USDT Risk / Absolute Entry-to-SL Distance
```

The backend recomputes RR and validates price geometry:

```text
Long:  SL < Entry < TP
Short: TP < Entry < SL
```

A submitted RR value cannot override the backend calculation.

---

## Dynamic risk capacity

At BDT day start:

```text
Base Risk Pool = Day-start equity × 5%
```

The effective pool changes with exact realized PnL:

```text
Effective Risk Pool = Base Risk Pool + Net Realized PnL Today
Available Risk = Effective Risk Pool - Current Live Downside Risk
```

Examples using 1,000 USDT day-start equity:

```text
Base pool: 50 USDT
Realized profit: +10 USDT
Live downside risk: 20 USDT
Available risk: 40 USDT
```

```text
Base pool: 50 USDT
Realized loss: -20 USDT
Live downside risk: 10 USDT
Available risk: 20 USDT
```

### Live risk release

The engine recalculates live downside risk from the current protective stop and remaining position quantity.

- Original SL still below/above entry: remaining downside risk is counted.
- SL moved to break-even: live downside risk becomes **0**.
- SL moved into profit: live downside risk remains **0**.
- Partial TP profit is synchronized and can increase the remaining risk capacity.

---

## Position sizing and margin rules

The sizing engine validates:

- fresh account equity and available balance;
- SL distance;
- exchange quantity step;
- exchange tick size;
- minimum order quantity;
- minimum notional;
- fixed USDT risk tolerance;
- current authoritative exchange-position margin;
- total 50% portfolio margin ceiling.

### Margin formula

```text
Required Margin = Position Notional / Selected Leverage
```

For fixed-risk trades, the approved profile leverage is selected:

- Scalping: up to 20x
- Intraday: up to 10x

The 50% exposure limit is a **hard combined ceiling**. The engine must not reduce leverage merely to make one trade consume the remaining exposure budget.

Example:

```text
Position value: 3,660 USDT
Scalping leverage: 20x
Approximate required margin: 183 USDT
```

The trade is rejected when the profile leverage cannot fit the position within available balance or remaining portfolio capacity.

---

## Authoritative execution flow

Every new trade follows one execution path:

```text
Signal
  -> fresh wallet and exchange positions
  -> executable quote
  -> backend RR / geometry validation
  -> fixed-risk position sizing
  -> atomic risk and active-trade reservation
  -> leverage configuration
  -> market order submission
  -> exchange fill confirmation
  -> actual average entry and quantity persistence
  -> actual-fill risk and RR recheck
  -> initial SL / runner TP attachment
  -> exchange protection verification
  -> native TP1 / TP2 installation
  -> active trade confirmation
```

### Execution safety controls

- Deterministic execution key and Bybit `orderLinkId`
- Durable reservation before order submission
- Duplicate execution rejection
- Atomic reservation of:
  - execution key;
  - active-trade slot;
  - symbol exclusivity;
  - dynamic risk capacity
- Network/timeout recovery by deterministic order lookup
- Uncertain orders are not reported as successful
- Actual fill price and executed quantity are authoritative
- Unsafe fill risk or RR triggers an emergency reduce-only close
- SL/TP protection is verified from the exchange position
- Protection failure triggers emergency close and exact close reconciliation

---

## Native profit-taking and trade management

The exchange, not a slow polling loop, owns the primary TP1 and TP2 triggers.

| Stage | Target | Quantity | Result |
|---|---:|---:|---|
| TP1 | 2R | 50% | Profit booked; remaining SL moves to actual entry / break-even |
| TP2 | 2.5R | 25% | Second profit booked; trailing protection activates |
| Runner | 3R | Remaining 25% | Managed by verified runner protection / trailing logic |

### Native order behavior

- TP1 and TP2 are GTC reduce-only exchange orders.
- Deterministic order IDs are persisted in the journal.
- A dedicated watcher reconciles order state every **2 seconds**.
- Position-size reconciliation is a restart-safe fallback when order history is delayed.
- Native orders prevent duplicate polling-based partial closes.
- If a native order is cancelled, rejected or deactivated, the controlled legacy mark-price fallback is enabled.
- Eligible full-size active trades can be adopted into native TP management after deployment/restart.
- A previously missed wick cannot be reconstructed retroactively.

---

## Persistence and recovery

Persistent state includes:

- BDT day-start equity;
- realized PnL today;
- live downside risk;
- base/effective/available risk pools;
- circuit-breaker status and reason;
- symbol cooldown expiries;
- active trade count and symbols;
- execution keys and order IDs;
- actual fill evidence;
- selected leverage and sizing evidence;
- SL/TP protection evidence;
- TP1/TP2 native order state;
- management state and remaining quantity;
- exact close/PnL synchronization state.

PostgreSQL is the production authority. SQLite is intended only for local development.

---

## Local run

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

## Required manual secrets

### Backend environment

- `ADMIN_USERNAME`
- `ADMIN_PASSWORD_HASH`
- `SESSION_SECRET`
- `BYBIT_DEMO_API_KEY`
- `BYBIT_DEMO_API_SECRET`
- `BYBIT_LIVE_API_KEY`
- `BYBIT_LIVE_API_SECRET`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

### Frontend environment

- `VITE_API_BASE_URL`

Secrets must never be committed to the repository.

---

## Render deployment

`render.yaml` defines:

- `drayfrogd-backend`, using Linux-safe Python commands;
- `drayfrogd-frontend`, using a deterministic `npm ci` build;
- `drayfrogd-db`, a managed Render PostgreSQL database;
- `DATABASE_URL`, injected from the database private connection string;
- `APP_ENV=production`, which rejects accidental production SQLite usage.

### Deployment sequence

1. Merge the approved and CI-passing commit into `main`.
2. Allow Render to deploy the new main commit.
3. Supply every environment variable marked `sync: false`.
4. Set `VITE_API_BASE_URL` to the deployed backend URL.
5. Confirm the backend startup log contains `Database bootstrap complete`.
6. Confirm `/health` succeeds.
7. Restart the backend and verify journal and risk records remain available.
8. Run the Bybit Demo verification checklist below.

### Render Free PostgreSQL limitation

The Blueprint currently requests Render's `free` PostgreSQL plan. It persists data across normal backend redeploys, but the free database has a limited lifetime and is not suitable for permanent production retention. Upgrade the database plan before expiry or migrate the data to another persistent PostgreSQL provider.

### Existing SQLite data

Switching to PostgreSQL prevents future backend redeploys from losing database state. Existing records in an old SQLite file are not copied automatically. Export and migrate any records that must be retained before replacing the database.

---

## Required Bybit Demo runtime verification

After the latest main commit deploys, verify one fresh scalping trade end-to-end:

1. Risk amount is approximately 20 USDT.
2. Selected leverage is 20x unless the exchange applies a stricter instrument limit.
3. Required margin does not consume the full 50% portfolio budget.
4. Actual average fill price and executed quantity appear in the journal.
5. Initial SL and runner TP are attached and verified.
6. TP1 and TP2 reduce-only orders appear in Bybit Open Orders.
7. TP1 fill closes approximately 50% and moves remaining SL to break-even.
8. TP2 fill closes approximately 25% and activates trailing protection.
9. Remaining quantity and realized PnL synchronize correctly.
10. A negative final realized result starts the 30-minute symbol cooldown.
11. Net realized loss reaching 5% of BDT day-start equity stops new execution.
12. Restart the backend and confirm state and native order reconciliation remain correct.

Do not describe the engine as runtime-verified until this checklist has real exchange evidence.

---

## Current known boundary

The codebase and CI currently support the documented risk, execution and trade-management contract. The following still requires real environment evidence:

- complete Bybit Demo order-to-fill-to-native-TP lifecycle;
- protection updates after actual TP1/TP2 fills;
- restart recovery against real exchange order history;
- Render deployment logs for the latest merged main commit.

Live trading should remain disabled until Demo runtime verification is completed and reviewed.

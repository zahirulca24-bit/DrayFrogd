# DayForge V2 — Runtime Update

> **Date:** 13 July 2026 (BDT)  
> **Status:** Documentation update only — no product-code fix is claimed.

## Newly observed deployed-runtime evidence

The Product Owner reported that Bybit showed **7 open trades in the morning**, but later the application no longer provided a complete and reliable account of those trade outcomes.

Observed application symptoms from the supplied screenshots:

- Active Trades showed one exchange-synced `LABUSDT` position at one point.
- Dashboard, Active Trades, Journal, and exchange-derived values were not consistently presenting one complete lifecycle view.
- Journal did not provide enough exact close evidence to determine why the earlier trades closed or whether Stop Loss was the cause.
- Without complete close evidence, no Stop Loss root-cause diagnosis or strategy/risk correction is considered reliable.

## Current priority — `JOURNAL-CLOSE-SYNC-001`

No further strategy, signal, or risk-policy change should be made until the Journal and close-synchronization path is repaired and verified.

Required persistence for every completed trade:

- exact exit price
- realized PnL
- trading fees
- close reason and close source
- SL/TP event identity where available
- original SL and final SL
- strategy name
- trade type and timeframe
- entry timestamp and close timestamp
- protection state and lifecycle evidence

Required behavior:

1. Missing exact close data must not be treated as a fully reconciled final close.
2. A pending close must remain retryable until exact exchange evidence is persisted or an explicit terminal exception is recorded.
3. Restart/fallback reconciliation must persist the full close payload even when the original in-memory trade object is unavailable.
4. Supabase/database persistence failures must be visible and auditable; they must not be silently swallowed.
5. Dashboard, Active Trades, Journal, and Bybit must converge to the same authoritative result.

## Verification gate

This repair must not be described as fixed or complete until a fresh Bybit Demo lifecycle proves all of the following:

- trade open creates a Journal lifecycle record
- SL/TP/manual close stores exact exit, fee, PnL, reason, and timestamps
- delayed close evidence is retried and later persisted
- backend restart does not lose or duplicate the lifecycle
- Bybit, Dashboard, Active Trades, and Journal show matching results
- evidence is retained after repeated browser refreshes

## Current verdict

`JOURNAL-CLOSE-SYNC-001` is **OPEN / NOT FIXED**.

Previous automated tests and earlier realized-PnL runtime evidence do not prove complete Journal close evidence for the newly observed seven-trade lifecycle. No Stop Loss root cause is claimed from incomplete evidence.

---

## Independent ZIP Audit — 13 July 2026

**Audited artifact:** `DayForge-Forge-Better-Trading-Every-Day-main.zip`  
**Reported SHA-256:** `766faa42f947422591067ebab34d02767d362dc83b73c43b44ed51ba8bcdc338`  
**Reported scope:** 211 files; 106 Python/TypeScript source and test files; approximately 26,366 source/test lines.

### External audit verdict

**NOT PRODUCTION-SAFE YET.** The external audit reported that compilation, backend tests, frontend TypeScript checks, frontend production build, and npm dependency audit passed, but the built-in backend validation failed and real Bybit/Render runtime verification was not performed.

These findings are recorded as **external audit findings pending repository-by-repository confirmation**. They must not be represented as independently confirmed defects until each cited path and behavior is re-verified against the current repository head.

| ID | Severity | Reported finding | Current tracking status |
|---|---|---|---|
| F-01 | HIGH | Live-capital execution lacks a separate fail-closed deployment approval gate | Pending repository verification |
| F-02 | HIGH | Authentication sessions lack expiry, server-side logout/revocation, and login throttling | Pending repository verification |
| F-03 | HIGH | Public readiness/status endpoints may invoke or expose private exchange state | Pending repository verification |
| F-04 | MEDIUM | `python -m app.validation` is stale and fails | Pending repository verification |
| F-05 | MEDIUM | Unknown trade types may silently fall back to Scalping | Pending repository verification |
| F-06 | MEDIUM | Frontend/backend signal metadata and protection-truth contract is incomplete | Pending repository verification |
| F-07 | LOW | Dependency pinning, integration coverage, and cleanup debt remain | Pending repository verification |

### Reported validation summary

| Check | External audit result |
|---|---|
| Python compile | PASS |
| Backend unit tests | 203/203 PASS |
| Frontend TypeScript check | PASS |
| Frontend production build | PASS |
| npm dependency audit | 0 known vulnerabilities reported during that audit |
| Built-in backend validation | FAIL |
| Real Bybit/Render runtime verification | NOT RUN / NOT PROVEN |

### Required repair order

1. Repair and verify `JOURNAL-CLOSE-SYNC-001` so exact exit, fee, realized PnL, close reason, SL/TP evidence, and restart recovery are auditable.
2. Add a separate fail-closed live-trading release gate.
3. Add session expiry, server-side revocation/logout, and login throttling.
4. Protect and redesign readiness/status endpoints; retain only minimal public liveness.
5. Repair `app.validation` and include it in CI.
6. Remove silent unknown-profile fallback and require explicit attention state or evidence-backed recovery.
7. Repair frontend/backend signal metadata contracts and protection truth flags.
8. Add integration tests and then run controlled Bybit Demo and Render verification.

### Release classification

| Area | Current classification |
|---|---|
| Buildability | PASS reported by external audit |
| Backend unit suite | PASS reported by external audit |
| Frontend compile/build | PASS reported by external audit |
| Internal validation gate | FAIL reported by external audit |
| Journal exact close lifecycle | OPEN / NOT FIXED |
| Authentication hardening | BLOCKED pending verification and repair |
| Live-capital safety lock | BLOCKED pending verification and repair |
| Public operational endpoint security | BLOCKED pending verification and repair |
| Exchange/WebSocket runtime | UNVERIFIED |
| Production release | BLOCKED |

**Current project verdict:** DayForge remains **Demo Beta / Engineering Verification** and is **not production-ready**. No live-capital approval is granted.
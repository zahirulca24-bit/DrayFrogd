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

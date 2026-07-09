# Repository Audit

Audit date: 2026-07-10

## Scope

This audit reviewed the current FastAPI backend, React/Vite frontend, automated CI checks, and the proposed patch supplied for review.

## Verified baseline checks

The repository CI workflow runs these checks:

- Backend dependency installation
- Python compile check for `app` and `tests`
- Backend unit-test discovery
- Frontend dependency installation
- Frontend TypeScript check
- Frontend production build

The most recent merged baseline passed all configured backend and frontend CI checks.

## Safe change accepted from the proposed patch

### Background event logging isolation

`app/background_worker.py` now wraps bot-event persistence with `_safe_log_bot_event`.

This prevents a database or journaling failure from crashing or interrupting the scanner, trade-management, or auto-execution loop. Persistence failures are still emitted through the application logger.

## Proposed changes not applied

### Journal ID change

The collision-resistant journal-ID proposal is valid, but it was not included in this patch because it requires a separate targeted test covering uniqueness and database compatibility.

### Performance and trade-history transformations

The proposed frontend transformations were not applied because they introduced incorrect financial reporting behavior:

- Open trades could be classified as `LOSS` when no realized result existed.
- Realized PnL could be fabricated as fixed `+2` or `-1` values.
- Existing real history could be discarded whenever any journal record existed.
- Missing exit prices could be replaced with take-profit values, which would misstate execution results.

Financial performance views must display only persisted or exchange-derived realized values. Missing values must remain unavailable rather than being synthesized.

## Remaining gaps

1. Add frontend automated tests for API mapping and core views.
2. Add backend tests for background-worker event-persistence failures.
3. Add versioned database migrations for journal and bot-event tables.
4. Add explicit persisted fields for realized PnL, fees, exit price, and strategy name before journal records are used as the sole performance-data source.

## Current conclusion

The accepted worker change is low-risk and improves runtime resilience. The rejected frontend portion must be redesigned around real persisted execution data before it is safe to merge.

# Repository Audit

Audit date: 2026-07-10

## Scope

This audit reviewed the current FastAPI backend, React/Vite frontend, configured CI checks, and the journal/performance patch that was merged through PR #2.

## Verified checks

The repository CI workflow covers:

- Backend dependency installation
- Python compile checks for `app` and `tests`
- Backend unit-test discovery
- Frontend dependency installation
- Frontend TypeScript validation
- Frontend production build

The latest validated branch run passed all configured backend and frontend checks.

## Verified safe changes

### Background event logging isolation

`app/background_worker.py` wraps bot-event persistence with `_safe_log_bot_event` so database or journal failures do not terminate scanner, trade-management, or auto-execution processing.

### Journal identifier strengthening

Journal IDs now combine a UTC microsecond timestamp with a random UUID suffix, reducing collision risk compared with millisecond-only IDs.

## Data-integrity risks requiring correction

The frontend journal transformation merged through PR #2 contains financial-reporting risks:

1. A journal record without a recognized profit result can be mapped to `LOSS`, including open or incomplete records.
2. Closed journal records can receive synthetic PnL values of fixed `+2` or `-1` instead of persisted realized PnL.
3. A missing exit price can be replaced by take-profit, which can misstate the actual execution result.
4. Whenever any journal records exist, the existing trade-history source can be discarded entirely.
5. Strategy names, leverage, margin, and other values can be filled with defaults rather than exchange-derived or persisted values.

Performance and history screens must only display persisted or exchange-derived realized values. Missing financial fields must remain unavailable until the backend stores them explicitly.

## Required next corrections

1. Persist realized PnL, realized fees, actual exit price, strategy name, and leverage in the journal schema.
2. Represent open, closed, profit, loss, and unknown results separately.
3. Never infer a loss from a missing result.
4. Never synthesize realized PnL or exit price.
5. Add mapping tests for open trades, unknown results, partial closes, TP exits, SL exits, and missing metadata.
6. Add frontend automated tests and versioned database migrations.

## Current conclusion

Backend logging resilience and stronger journal IDs are valid improvements. The merged frontend journal/performance mapping requires a dedicated correction before its financial metrics can be considered trustworthy.

# Evidence Register

Every project claim must use an evidence level. New evidence supersedes older evidence; it does not erase history.

## Evidence levels

- `CODE CONFIRMED`
- `TEST CONFIRMED`
- `CI CONFIRMED`
- `RUNTIME SCREENSHOT CONFIRMED`
- `RUNTIME LOG CONFIRMED`
- `SUSPECTED`
- `NOT TESTED`
- `CONTRADICTED`
- `SUPERSEDED`

## Current evidence

| Evidence ID | Claim | Level | Source | Current interpretation |
|---|---|---|---|---|
| EVD-001 | Periodic WebSocket-idle REST reconciliation is implemented | CODE + TEST CONFIRMED | PR #46, merged | REST truth refresh exists |
| EVD-002 | Backend suite passed after close-sync fixes | TEST CONFIRMED | 213/213 after PR #47 | Main automated baseline |
| EVD-003 | Public Bybit WebSocket displayed connected | RUNTIME SCREENSHOT CONFIRMED | 14 Jul 2026 screenshots | Public stream worked during captured window |
| EVD-004 | Private Bybit WebSocket displayed connected earlier | RUNTIME SCREENSHOT CONFIRMED | 14 Jul 2026 mobile screenshots | Private stream worked during captured window |
| EVD-005 | Private Bybit WebSocket later displayed connecting while system showed ready/healthy | RUNTIME SCREENSHOT CONFIRMED | 14 Jul 2026 desktop screenshots | Readiness degradation mismatch; Issue #54 |
| EVD-006 | Bybit transaction ledger is visible in Journal audit | RUNTIME SCREENSHOT CONFIRMED | 29 then 40 records displayed | Exchange ledger ingestion works at account level |
| EVD-007 | Journal rows lacked order ID/PnL source while Bybit showed real trades | RUNTIME SCREENSHOT CONFIRMED | Journal + Bybit transaction screenshots | Identity persistence/backfill incomplete; Issue #51 |
| EVD-008 | Unknown financial values displayed `N/A` | RUNTIME SCREENSHOT CONFIRMED | Journal/Performance screenshots | No fabricated zero for some unknown outcomes |
| EVD-009 | Bybit ledger showed about `-$61.7476` while bot remained RUNNING/AUTO ENABLED | RUNTIME SCREENSHOT CONFIRMED | 14 Jul 2026 desktop screenshots | 5% authoritative daily-loss circuit failed or used incomplete source; Issue #53 |
| EVD-010 | Dashboard/Active Trades showed about `+$13.0446` realized while Bybit ledger was negative | RUNTIME SCREENSHOT CONFIRMED | Same runtime window | Financial source mismatch; not strategy evidence |
| EVD-011 | Risk/trade displayed `2.15%` on Control Center and `1.00%` on Dashboard | RUNTIME SCREENSHOT CONFIRMED | 14 Jul 2026 screenshots | Configuration source drift; Issue #55 |
| EVD-012 | Control Center displayed primary Journal storage as SQLite on Render | RUNTIME SCREENSHOT CONFIRMED | 14 Jul 2026 screenshot | Durability not proven; Issue #56 |
| EVD-013 | Performance showed W/L `1/0`, unknown `2`, but win rate `33.33%` | RUNTIME SCREENSHOT CONFIRMED | 14 Jul 2026 screenshots | Unknown outcomes contaminate metrics; Issue #57 |
| EVD-014 | Repeated active-symbol blocks created repeated warning incidents | RUNTIME SCREENSHOT CONFIRMED | NEARUSDT incident screenshots | Expected guard is logged as repeated failure; Issue #58 |
| EVD-015 | Exact PnL matching branch tests passed | TEST CONFIRMED | PR #48 | Not runtime-verified and not merged |
| EVD-016 | State classification branch tests passed | TEST CONFIRMED | PR #49 | Not runtime-verified and not merged |
| EVD-017 | Authentication hardening branch tests/build passed | TEST CONFIRMED | PR #50 | Not runtime-verified and not merged |
| EVD-018 | A Strategy Backtest Engine UI is deployed with symbol, strategy, candle-count, risk, fee and RR controls | RUNTIME SCREENSHOT CONFIRMED | Settings screenshot, 14 Jul 2026 | Proves UI/endpoint availability only |
| EVD-019 | Backtest/live strategy equivalence, no-look-ahead correctness and deterministic simulation | NOT TESTED | Issue #59 opened | Strategy validity cannot currently be claimed |
| EVD-020 | Product Owner made backtest and strategy validity the highest product-value priority | OWNER DECISION CONFIRMED | DEC-016, 14 Jul 2026 | Settings consolidation is deferred until after backtest audit |

## Prohibited conclusions

The current evidence does **not** prove:

- that the trading strategy itself caused every live loss;
- that the deployed backtest is correct because its page renders;
- that backtest results use the exact live strategy implementation;
- that a short profitable backtest proves strategy robustness;
- that a missing Journal order ID means Bybit rejected the trade;
- that a connected badge proves full lifecycle correctness;
- that a passing CI suite proves Render runtime correctness;
- that account-level ledger rows can be safely assigned to a Journal trade without exact identity;
- that live-capital trading is safe.

## Adding evidence

Each new entry must include:

```text
Evidence ID:
Claim:
Timestamp/timezone:
Level:
Source:
Observed fact:
Inference, if any:
Related task/issue:
Supersedes:
```

Facts and inferences must be written separately.

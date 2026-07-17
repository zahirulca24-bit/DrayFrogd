# P0-0 Trade Churn Rule Lock

## Authoritative rule

Daily trade count is reporting only. It is not a hard execution blocker.

`max_daily_trades=0` means no hard count cap.

The bot must not sleep or reject a trade only because the daily trade count is above 8.

## Mandatory safety gates retained

The removal of the hard daily count cap does not remove execution safety. These gates remain authoritative:

1. Active trade cap.
2. Same-symbol active-position block.
3. Same-symbol re-entry cooldown.
4. Dynamic risk capacity.
5. Daily net realized loss circuit breaker.
6. Duplicate execution-key block.

## Superseded rule

The old 8-trade-per-BDT-day cap is superseded by PR #93 and Issue #65 P0-0 reconciliation. Do not rebuild it unless the Product Owner explicitly re-approves a hard daily count cap.

## Verification required

- `DAILY_TRADE_LIMIT_REACHED` must not be treated as an expected execution guard.
- Same-symbol cooldown must still block re-entry.
- Active trade cap must remain an expected execution guard.
- Dynamic risk capacity must remain an expected execution guard.
- Failed/rejected execution attempts must not pollute completed-trade metrics.

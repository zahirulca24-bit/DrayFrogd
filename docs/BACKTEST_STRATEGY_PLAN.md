# Backtest Strategy Validation Plan

## Product Owner priority

Backtest and strategy validity are the highest product-value priority. Settings consolidation and other UI refinements follow after the strategy/backtest engine is proven trustworthy.

Runtime safety findings remain separate. This plan does not authorize any change to the bot's start, stop, pause or resume state; those actions require explicit Product Owner approval.

## Active task

`BACKTEST-STRATEGY-TRUTH-001` — Issue #59

## Phase 1 — Audit

- Map live scanner/strategy functions to backtest functions.
- Verify candle source, timeframe coverage, ordering, pagination and closed-candle rules.
- Detect duplicated/simplified strategy logic.
- Detect look-ahead, future-indicator or same-candle leakage.
- Verify entry timing, SL/TP ordering, fees and risk model.
- Produce a live-versus-backtest equivalence table with file/test evidence.

## Phase 2 — Deterministic simulator

- Reuse canonical live strategy logic.
- Replay candles sequentially.
- Keep Scalping and Intraday pipelines separate.
- Persist every simulated trade with complete entry/exit/fee/PnL/R evidence.
- Make dataset provenance and configuration visible.
- Guarantee reproducible output for identical input.

## Phase 3 — Strategy evaluation

- Net PnL after fees
- Win rate from known terminal outcomes only
- Profit factor
- Maximum drawdown
- Expectancy and average R
- Consecutive wins/losses
- Symbol/session/direction/strategy/regime breakdown
- Out-of-sample or walk-forward evidence

No strategy is approved from a short profitable run. Minimum sample size, test period and approval thresholds require explicit Product Owner approval after the baseline audit.

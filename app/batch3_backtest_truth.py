from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import wraps
from math import isfinite
from typing import Any, Callable

_INSTALLED = False
_ORIGINAL_RUN: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_SIMULATE: Callable[..., dict[str, Any] | None] | None = None
_ORIGINAL_TIMESTAMP: Callable[[dict[str, Any]], datetime | None] | None = None


def install() -> None:
    """Harden the research simulator without changing live strategy or execution rules."""

    global _INSTALLED, _ORIGINAL_RUN, _ORIGINAL_SIMULATE, _ORIGINAL_TIMESTAMP
    if _INSTALLED:
        return

    import app.backtest as backtest

    original_run = backtest.run_strategy_backtest
    original_simulate = backtest._simulate_trade
    original_timestamp = backtest._timestamp
    _ORIGINAL_RUN = original_run
    _ORIGINAL_SIMULATE = original_simulate
    _ORIGINAL_TIMESTAMP = original_timestamp

    @wraps(original_timestamp)
    def closed_candle_timestamp(candle: dict[str, Any]) -> datetime | None:
        if isinstance(candle, dict):
            annotated = candle.get("_backtest_close_timestamp")
            if annotated:
                return _parse_timestamp(annotated)
        return original_timestamp(candle)

    @wraps(original_run)
    def deterministic_closed_candle_run(client: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_run(_ClosedCandleClientProxy(client), *args, **kwargs)
        if not isinstance(result, dict):
            return result
        payload = dict(result)
        parity = dict(payload.get("live_pipeline_parity") or {})
        parity.update(
            closed_candle_only=True,
            decision_time="trigger_candle_close",
            higher_timeframes_require_close_before_decision=True,
            entry_timing="next_trigger_candle_open",
            dataset_order_validation=True,
            duplicate_candle_rejection=True,
            missing_candle_rejection=True,
            fee_model="entry_notional_plus_exit_notional",
        )
        payload["live_pipeline_parity"] = parity
        payload["dataset_truth"] = {
            "timestamp_semantics": "source_open_time_with_annotated_close_time",
            "signal_decision": "after_trigger_candle_close",
            "entry_fill": "next_trigger_candle_open",
            "same_candle_sl_tp": "conservative_stop_first",
            "fees": "entry_and_exit_notional",
        }
        return payload

    backtest._timestamp = closed_candle_timestamp
    backtest._simulate_trade = _simulate_trade_next_open
    backtest.run_strategy_backtest = deterministic_closed_candle_run
    _INSTALLED = True


class _ClosedCandleClientProxy:
    def __init__(self, client: Any) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def safe_fetch_recent_candles(self, symbol: str, interval: str, limit: int):
        ok, candles, error = self._client.safe_fetch_recent_candles(symbol, interval=interval, limit=limit)
        if not ok:
            return ok, candles, error
        try:
            minutes = max(1, int(str(interval)))
            normalized = _validate_and_annotate_dataset(list(candles or []), minutes)
        except (TypeError, ValueError) as exc:
            return False, [], f"BACKTEST_DATASET_INVALID: {exc}"
        return True, normalized, None


def _validate_and_annotate_dataset(candles: list[dict[str, Any]], interval_minutes: int) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    previous: datetime | None = None
    expected_delta = timedelta(minutes=interval_minutes)

    for index, candle in enumerate(candles):
        if not isinstance(candle, dict):
            raise ValueError(f"candle_{index}_not_object")
        opened_at = _parse_timestamp(candle.get("timestamp"))
        if opened_at is None:
            raise ValueError(f"candle_{index}_timestamp_invalid")
        if previous is not None:
            delta = opened_at - previous
            if delta <= timedelta(0):
                reason = "duplicate_timestamp" if delta == timedelta(0) else "out_of_order_timestamp"
                raise ValueError(f"{reason}_at_{index}")
            if abs((delta - expected_delta).total_seconds()) > 1.0:
                raise ValueError(f"missing_or_irregular_candle_before_{index}")
        _validate_ohlc(candle, index)
        item = dict(candle)
        item["_backtest_interval_minutes"] = interval_minutes
        item["_backtest_close_timestamp"] = (opened_at + expected_delta).isoformat()
        normalized.append(item)
        previous = opened_at

    return normalized


def _validate_ohlc(candle: dict[str, Any], index: int) -> None:
    values = {name: _number(candle.get(name)) for name in ("open", "high", "low", "close")}
    if any(value is None for value in values.values()):
        raise ValueError(f"candle_{index}_ohlc_invalid")
    open_price = float(values["open"])
    high = float(values["high"])
    low = float(values["low"])
    close = float(values["close"])
    if low > high or high < max(open_price, close) or low > min(open_price, close):
        raise ValueError(f"candle_{index}_ohlc_geometry_invalid")


def _simulate_trade_next_open(
    signal: dict[str, Any],
    candles: list[dict[str, Any]],
    *,
    start_index: int,
    risk_amount: float,
    fee_rate: float,
    max_hold_candles: int,
) -> dict[str, Any] | None:
    direction = str(signal.get("direction") or "").lower()
    planned_entry = _number(signal.get("entry"))
    stop = _number(signal.get("stop_loss"))
    target = _number(signal.get("take_profit"))
    if direction not in {"long", "short"} or planned_entry is None or stop is None or target is None:
        return None
    if start_index < 0 or start_index >= len(candles):
        return None

    fill_candle = candles[start_index]
    entry = _number(fill_candle.get("open"))
    if entry is None:
        return None
    if direction == "long" and not stop < entry < target:
        return None
    if direction == "short" and not target < entry < stop:
        return None

    risk_distance = abs(entry - stop)
    reward_distance = abs(target - entry)
    if risk_distance <= 0 or reward_distance <= 0:
        return None
    quantity = risk_amount / risk_distance
    actual_rr = reward_distance / risk_distance
    entry_fee = abs(entry * quantity) * max(fee_rate, 0.0)
    max_exit_index = min(len(candles), start_index + max_hold_candles)

    for exit_index in range(start_index, max_exit_index):
        candle = candles[exit_index]
        high = _number(candle.get("high"))
        low = _number(candle.get("low"))
        if high is None or low is None:
            continue

        if direction == "long":
            stop_hit = low <= stop
            target_hit = high >= target
        else:
            stop_hit = high >= stop
            target_hit = low <= target
        if not stop_hit and not target_hit:
            continue

        # OHLC cannot prove intra-candle ordering. If both print, assume the loss first.
        result = "loss" if stop_hit else "win"
        exit_price = stop if stop_hit else target
        gross_pnl = ((exit_price - entry) if direction == "long" else (entry - exit_price)) * quantity
        exit_fee = abs(exit_price * quantity) * max(fee_rate, 0.0)
        fees = entry_fee + exit_fee
        net_pnl = gross_pnl - fees
        close_time = candle.get("_backtest_close_timestamp") or candle.get("timestamp")
        return {
            "strategy": signal.get("strategy_name") or signal.get("strategy"),
            "trade_type": signal.get("trade_type"),
            "engine_profile": signal.get("engine_profile"),
            "direction": direction,
            "planned_entry": planned_entry,
            "entry": entry,
            "entry_slippage": entry - planned_entry,
            "stop_loss": stop,
            "take_profit": target,
            "exit_price": exit_price,
            "result": result,
            "exit_reason": "stop_loss" if stop_hit else "take_profit",
            "diagnosis": (
                "SL_AND_TP_SAME_CANDLE_CONSERVATIVE_SL_FIRST"
                if stop_hit and target_hit
                else "STOP_LEVEL_TOUCHED"
                if stop_hit
                else "TAKE_PROFIT_TOUCHED"
            ),
            "signal_time": signal.get("detected_at"),
            "opened_at": fill_candle.get("timestamp"),
            "closed_at": close_time,
            "exit_index": exit_index,
            "risk_reward": round(actual_rr, 8),
            "strategy_risk_reward": signal.get("risk_reward"),
            "quantity": quantity,
            "gross_pnl": gross_pnl,
            "entry_fee": entry_fee,
            "exit_fee": exit_fee,
            "fees": fees,
            "net_pnl": net_pnl,
            "pnl_r": net_pnl / risk_amount if risk_amount else 0.0,
            "gross_r": gross_pnl / risk_amount if risk_amount else 0.0,
            "trend_state": signal.get("trend_state"),
            "signal_state": signal.get("signal_state"),
            "profile_adjusted_target": signal.get("profile_adjusted_target"),
        }
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None

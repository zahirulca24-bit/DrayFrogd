from __future__ import annotations

from datetime import datetime
from math import ceil, isfinite
from typing import Any, Callable

from app.engines import evaluate_engine_strategies, get_engine_profile
from app.exchange import BybitClient
from app.scanner_logic import evaluate_multitimeframe_logic
from app.scanner_trend import TREND_DOWN, TREND_UP, analyze_trend
from app.signal_pipeline import SIGNAL_ACTIVE, normalize_strategy_result
from app.strategy import evaluate_registered_strategies, get_strategy_registry


StrategyEvaluator = Callable[[str, list[dict[str, Any]], list[dict[str, Any]], datetime | None], list[dict[str, Any]]]


def run_strategy_backtest(
    client: BybitClient,
    *,
    symbol: str,
    strategy: str = "all",
    trade_type: str = "scalping",
    candle_limit: int = 1000,
    candle_offset: int = 0,
    risk_amount: float | None = None,
    fee_bps: float = 5.5,
    min_risk_reward: float | None = None,
    max_hold_candles: int | None = None,
) -> dict[str, Any]:
    normalized_symbol = str(symbol or "").upper().strip()
    normalized_strategy = str(strategy or "all").lower().strip()
    normalized_trade_type = str(trade_type or "scalping").lower().strip()
    if normalized_trade_type not in {"scalping", "intraday"}:
        return {"ok": False, "error": "trade_type must be scalping or intraday"}

    profile = _profile_config(normalized_trade_type)
    resolved = _resolve_backtest_parameters(
        profile,
        risk_amount=risk_amount,
        min_risk_reward=min_risk_reward,
        max_hold_candles=max_hold_candles,
    )
    limit = max(260, min(int(candle_limit or 1000), 3000))
    offset = max(0, min(int(candle_offset or 0), 5000))
    risk_usdt = resolved["risk_amount"]
    rr_floor = resolved["min_risk_reward"]
    hold_limit = resolved["max_hold_candles"]
    fee_rate = max(float(fee_bps or 0.0), 0.0) / 10_000

    trigger_fetch_limit = min(5000, limit + offset)
    ok_trigger, trigger_raw, trigger_error = client.safe_fetch_recent_candles(
        normalized_symbol,
        interval=profile["trigger_interval"],
        limit=trigger_fetch_limit,
    )
    if not ok_trigger:
        return {"ok": False, "error": trigger_error or f"{profile['trigger_label']} candles unavailable"}
    candles_trigger = _window_with_offset(trigger_raw, limit=limit, offset=offset)

    setup_limit = max(260, min(3000, (limit // profile["setup_ratio"]) + offset + 260))
    ok_setup, candles_setup, setup_error = client.safe_fetch_recent_candles(
        normalized_symbol,
        interval=profile["setup_interval"],
        limit=setup_limit,
    )
    if not ok_setup:
        return {"ok": False, "error": setup_error or f"{profile['setup_label']} candles unavailable"}

    trend_limit = max(260, min(1000, (limit // profile["trend_ratio"]) + offset + 260))
    ok_trend, candles_trend, trend_error = client.safe_fetch_recent_candles(
        normalized_symbol,
        interval=profile["trend_interval"],
        limit=trend_limit,
    )
    if not ok_trend:
        return {"ok": False, "error": trend_error or f"{profile['trend_label']} candles unavailable"}

    if len(candles_trigger) < 80 or len(candles_setup) < 220 or len(candles_trend) < 55:
        return {
            "ok": False,
            "error": "Not enough candle history for strategy warm-up",
            "candles_trigger": len(candles_trigger),
            "candles_setup": len(candles_setup),
            "candles_trend": len(candles_trend),
        }

    trades: list[dict[str, Any]] = []
    equity_curve = [0.0]
    skipped_signals = 0
    skipped_by_reason: dict[str, int] = {}
    signal_checks = 0
    last_signal_key: str | None = None
    index = 40

    while index < len(candles_trigger) - 2:
        now = _timestamp(candles_trigger[index])
        if now is None:
            index += 1
            continue

        window_trigger = candles_trigger[: index + 1]
        window_setup = [candle for candle in candles_setup if (_timestamp(candle) or now) <= now]
        window_trend = [candle for candle in candles_trend if (_timestamp(candle) or now) <= now]
        if len(window_setup) < 220 or len(window_trend) < 55:
            index += 1
            continue

        trend = analyze_trend(
            window_trend,
            interval_minutes=profile["trend_minutes"],
            now=now,
        )
        trend_state = str(trend.get("state") or "")
        if trend_state not in {TREND_UP, TREND_DOWN}:
            skipped_signals += 1
            _increment(skipped_by_reason, f"trend_{trend_state.lower() or 'not_eligible'}")
            index += 1
            continue

        scanner_logic = _scanner_logic(
            normalized_trade_type,
            normalized_symbol,
            window_setup,
            window_trigger,
            trend,
        )
        signal, normalized_results = _evaluate_profiled_signal(
            normalized_strategy,
            normalized_symbol,
            normalized_trade_type,
            window_setup,
            window_trigger,
            now,
            trend=trend,
            scanner_logic=scanner_logic,
            timeframes=profile["timeframes"],
        )
        signal_checks += len(normalized_results)
        if signal is None:
            skipped_signals += 1
            _increment(skipped_by_reason, _best_rejection_reason(normalized_results))
            index += 1
            continue
        if float(signal.get("risk_reward") or 0.0) + 1e-9 < rr_floor:
            skipped_signals += 1
            _increment(skipped_by_reason, "risk_reward_below_backtest_floor")
            index += 1
            continue

        signal_key = str(signal.get("signal_key") or "").strip() or "|".join(
            [
                str(signal.get("strategy_name") or signal.get("strategy") or normalized_strategy),
                str(signal.get("direction") or ""),
                str(signal.get("detected_at") or ""),
                str(signal.get("entry") or ""),
            ]
        )
        if signal_key == last_signal_key:
            _increment(skipped_by_reason, "duplicate_signal")
            index += 1
            continue
        last_signal_key = signal_key

        outcome = _simulate_trade(
            signal,
            candles_trigger,
            start_index=index + 1,
            risk_amount=risk_usdt,
            fee_rate=fee_rate,
            max_hold_candles=hold_limit,
        )
        if outcome is None:
            skipped_signals += 1
            _increment(skipped_by_reason, "no_exit_inside_profile_hold_window")
            index += 1
            continue
        trades.append(outcome)
        equity_curve.append(equity_curve[-1] + outcome["net_pnl"])
        index = max(outcome["exit_index"] + 1, index + 1)

    wins = [trade for trade in trades if trade["result"] == "win"]
    losses = [trade for trade in trades if trade["result"] == "loss"]
    net_pnl = sum(trade["net_pnl"] for trade in trades)
    gross_profit = sum(trade["net_pnl"] for trade in wins)
    gross_loss = abs(sum(trade["net_pnl"] for trade in losses))
    max_drawdown = _max_drawdown(equity_curve)

    return {
        "ok": True,
        "symbol": normalized_symbol,
        "strategy": normalized_strategy,
        "trade_type": normalized_trade_type,
        "profile": profile,
        "live_pipeline_parity": {
            "profile_engine": True,
            "trend_gate": True,
            "canonical_signal_gate": True,
            "profile_rr_gate": True,
            "management_simulation": "single_exit_conservative",
            "custom_parameter_override": not resolved["uses_canonical_defaults"],
        },
        "candles_1m": len(candles_trigger) if profile["trigger_interval"] == "1" else 0,
        "candles_5m": len(candles_trigger) if profile["trigger_interval"] == "5" else len(candles_setup) if profile["setup_interval"] == "5" else 0,
        "candles_trigger": len(candles_trigger),
        "candles_setup": len(candles_setup),
        "candles_trend": len(candles_trend),
        "candle_offset": offset,
        "risk_amount": risk_usdt,
        "fee_bps": fee_bps,
        "min_risk_reward": rr_floor,
        "max_hold_candles": hold_limit,
        "max_hold_minutes": hold_limit * profile["trigger_minutes"],
        "parameters": resolved,
        "summary": {
            "trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(trades) * 100.0) if trades else 0.0,
            "net_pnl": net_pnl,
            "pnl_r": (net_pnl / risk_usdt) if risk_usdt else 0.0,
            "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else None,
            "max_drawdown": max_drawdown,
            "skipped_signals": skipped_signals,
            "signal_checks": signal_checks,
            "skipped_by_reason": skipped_by_reason,
        },
        "trades": trades[-100:],
        "equity_curve": equity_curve[-300:],
    }


def _resolve_backtest_parameters(
    profile: dict[str, Any],
    *,
    risk_amount: float | None,
    min_risk_reward: float | None,
    max_hold_candles: int | None,
) -> dict[str, Any]:
    default_risk = float(profile["default_risk_amount"])
    default_rr = float(profile["default_min_risk_reward"])
    default_hold = int(profile["max_hold_candles"])

    selected_risk = default_risk if risk_amount is None else max(float(risk_amount), 1.0)
    requested_rr = default_rr if min_risk_reward is None else max(float(min_risk_reward), 0.0)
    selected_rr = max(default_rr, requested_rr)
    requested_hold = default_hold if max_hold_candles is None else max(5, int(max_hold_candles))
    selected_hold = min(requested_hold, default_hold)

    return {
        "risk_amount": selected_risk,
        "min_risk_reward": selected_rr,
        "max_hold_candles": selected_hold,
        "canonical_risk_amount": default_risk,
        "canonical_min_risk_reward": default_rr,
        "canonical_max_hold_candles": default_hold,
        "risk_override": abs(selected_risk - default_risk) > 1e-9,
        "rr_floor_raised": selected_rr > default_rr + 1e-9,
        "hold_limit_shortened": selected_hold < default_hold,
        "hold_limit_capped_to_profile": requested_hold > default_hold,
        "uses_canonical_defaults": (
            abs(selected_risk - default_risk) <= 1e-9
            and abs(selected_rr - default_rr) <= 1e-9
            and selected_hold == default_hold
        ),
    }


def _evaluate_profiled_signal(
    strategy: str,
    symbol: str,
    trade_type: str,
    candles_setup: list[dict[str, Any]],
    candles_trigger: list[dict[str, Any]],
    now: datetime,
    *,
    trend: dict[str, Any],
    scanner_logic: dict[str, Any],
    timeframes: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    evaluator = _strategy_evaluator(strategy)
    if evaluator is None:
        return None, [{"signal_state": "INVALID", "rejection_reason": "unknown_strategy"}]

    raw_results = evaluate_engine_strategies(
        trade_type,
        symbol=symbol,
        setup_candles=candles_setup,
        trigger_candles=candles_trigger,
        evaluator=evaluator,
        now=now,
    )
    normalized_results: list[dict[str, Any]] = []
    for raw in raw_results:
        normalized = normalize_strategy_result(
            symbol=symbol,
            result=raw,
            trade_type=trade_type,
            market_rank=1,
            trend=trend,
            market_ranking={"score": 0.0, "components": {"source": "historical_backtest"}},
            scanner_logic=scanner_logic,
            timeframes=timeframes,
        )
        for key in ("setup_timeframe_used", "setup_candle_count", "trigger_candle_count", "setup_detected_at"):
            if key in raw:
                normalized[key] = raw[key]
        normalized_results.append(normalized)

    active = [
        item
        for item in normalized_results
        if item.get("signal_state") == SIGNAL_ACTIVE and item.get("is_executable")
    ]
    active.sort(
        key=lambda item: (
            -float(item.get("signal_score") or 0.0),
            -float(item.get("confidence_score") or 0.0),
            str(item.get("strategy_name") or ""),
        )
    )
    return (active[0] if active else None), normalized_results


def _strategy_evaluator(strategy: str) -> StrategyEvaluator | None:
    if strategy == "all":
        return evaluate_registered_strategies
    definition = get_strategy_registry().get(strategy)
    if definition is None or not definition.enabled:
        return None

    def evaluate_one(
        symbol: str,
        candles_setup: list[dict[str, Any]],
        candles_trigger: list[dict[str, Any]],
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return [definition.evaluator(symbol, candles_setup, candles_trigger, now)]

    return evaluate_one


def _scanner_logic(
    trade_type: str,
    symbol: str,
    candles_setup: list[dict[str, Any]],
    candles_trigger: list[dict[str, Any]],
    trend: dict[str, Any],
) -> dict[str, Any]:
    trend_state = str(trend.get("state") or "")
    if trade_type == "intraday":
        return evaluate_multitimeframe_logic(
            symbol,
            candles_setup,
            candles_trigger,
            trend_state=trend_state,
        )
    direction = "long" if trend_state == TREND_UP else "short" if trend_state == TREND_DOWN else None
    return {
        "status": "eligible" if direction else "blocked",
        "direction": direction,
        "reason": "historical_profile_trend_eligible" if direction else "historical_profile_trend_blocked",
        "confidence_score": trend.get("strength"),
    }


def _simulate_trade(
    signal: dict[str, Any],
    candles: list[dict[str, Any]],
    *,
    start_index: int,
    risk_amount: float,
    fee_rate: float,
    max_hold_candles: int,
) -> dict[str, Any] | None:
    direction = str(signal.get("direction") or "").lower()
    entry = _number(signal.get("entry"))
    stop = _number(signal.get("stop_loss"))
    target = _number(signal.get("take_profit"))
    rr = _number(signal.get("risk_reward")) or 0.0
    if direction not in {"long", "short"} or entry is None or stop is None or target is None:
        return None
    risk_distance = abs(entry - stop)
    if risk_distance <= 0 or not isfinite(risk_distance):
        return None

    quantity = risk_amount / risk_distance
    notional = entry * quantity
    fees = notional * fee_rate * 2
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

        # If both levels print inside one candle, use the conservative stop-first assumption.
        result = "loss" if stop_hit else "win"
        exit_price = stop if stop_hit else target
        pnl_r = -1.0 if result == "loss" else rr
        gross_pnl = pnl_r * risk_amount
        net_pnl = gross_pnl - fees
        return {
            "strategy": signal.get("strategy_name") or signal.get("strategy"),
            "trade_type": signal.get("trade_type"),
            "engine_profile": signal.get("engine_profile"),
            "direction": direction,
            "entry": entry,
            "stop_loss": stop,
            "take_profit": target,
            "exit_price": exit_price,
            "result": result,
            "exit_reason": "stop_loss" if stop_hit else "take_profit",
            "diagnosis": _backtest_diagnosis(
                direction=direction,
                stop_hit=stop_hit,
                target_hit=target_hit,
                candle=candle,
                entry=entry,
                stop=stop,
                target=target,
            ),
            "opened_at": signal.get("detected_at") or candles[start_index - 1].get("timestamp"),
            "closed_at": candle.get("timestamp"),
            "exit_index": exit_index,
            "risk_reward": rr,
            "quantity": quantity,
            "gross_pnl": gross_pnl,
            "fees": fees,
            "net_pnl": net_pnl,
            "pnl_r": net_pnl / risk_amount if risk_amount else 0.0,
            "trend_state": signal.get("trend_state"),
            "signal_state": signal.get("signal_state"),
            "profile_adjusted_target": signal.get("profile_adjusted_target"),
        }
    return None


def _profile_config(trade_type: str) -> dict[str, Any]:
    profile = get_engine_profile(trade_type)
    setup_ratio = max(1, int(round(profile.setup_minutes / profile.trigger_minutes)))
    trend_ratio = max(1, int(round(profile.trend_minutes / profile.trigger_minutes)))
    max_hold_candles = max(1, int(ceil(profile.max_hold_seconds / (profile.trigger_minutes * 60))))
    return {
        "trade_type": profile.trade_type,
        "profile_name": profile.profile_name,
        "label": profile.trade_type.title(),
        "trend_interval": profile.trend_interval,
        "trend_label": profile.trend_label,
        "trend_minutes": profile.trend_minutes,
        "setup_interval": profile.setup_interval,
        "setup_label": profile.setup_label,
        "setup_minutes": profile.setup_minutes,
        "trigger_interval": profile.trigger_interval,
        "trigger_label": profile.trigger_label,
        "trigger_minutes": profile.trigger_minutes,
        "setup_ratio": setup_ratio,
        "trend_ratio": trend_ratio,
        "default_risk_amount": profile.risk_amount,
        "default_min_risk_reward": profile.min_risk_reward,
        "max_hold_candles": max_hold_candles,
        "max_hold_seconds": profile.max_hold_seconds,
        "timeframes": profile.timeframes(),
        "risk_contract": profile.risk_contract(),
        "management_contract": profile.management_contract(),
    }


def _window_with_offset(candles: list[dict[str, Any]], *, limit: int, offset: int) -> list[dict[str, Any]]:
    if offset <= 0:
        return candles[-limit:]
    end = max(len(candles) - offset, 0)
    start = max(end - limit, 0)
    return candles[start:end]


def _best_rejection_reason(results: list[dict[str, Any]]) -> str:
    for result in sorted(results, key=lambda item: -float(item.get("signal_score") or 0.0)):
        reason = str(result.get("rejection_reason") or "").strip()
        if reason:
            return reason
        state = str(result.get("signal_state") or "").strip().lower()
        if state:
            return state
    return "no_active_signal"


def _increment(counter: dict[str, int], key: str) -> None:
    normalized = str(key or "unknown").strip() or "unknown"
    counter[normalized] = counter.get(normalized, 0) + 1


def _backtest_diagnosis(
    *,
    direction: str,
    stop_hit: bool,
    target_hit: bool,
    candle: dict[str, Any],
    entry: float,
    stop: float,
    target: float,
) -> str:
    if stop_hit and target_hit:
        return "SL_AND_TP_SAME_CANDLE_CONSERVATIVE_SL_FIRST"
    if stop_hit:
        high = _number(candle.get("high"))
        low = _number(candle.get("low"))
        adverse = high if direction == "short" else low
        return (
            f"STOP_LEVEL_TOUCHED adverse={adverse} entry={entry} sl={stop} tp={target}"
            if adverse is not None
            else "STOP_LEVEL_TOUCHED"
        )
    return "TAKE_PROFIT_TOUCHED"


def _timestamp(candle: dict[str, Any]) -> datetime | None:
    value = candle.get("timestamp")
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def _max_drawdown(values: list[float]) -> float:
    peak = values[0] if values else 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value - peak)
    return worst

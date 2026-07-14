from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

from app.exchange import BybitClient
from app.strategy import evaluate_strategy_pipeline, get_strategy_registry


def run_strategy_backtest(
    client: BybitClient,
    *,
    symbol: str,
    strategy: str = "all",
    trade_type: str = "scalping",
    candle_limit: int = 1000,
    candle_offset: int = 0,
    risk_amount: float = 20.0,
    fee_bps: float = 5.5,
    min_risk_reward: float = 1.5,
    max_hold_candles: int = 240,
) -> dict[str, Any]:
    normalized_symbol = str(symbol or "").upper().strip()
    normalized_strategy = str(strategy or "all").lower().strip()
    normalized_trade_type = str(trade_type or "scalping").lower().strip()
    if normalized_trade_type not in {"scalping", "intraday"}:
        return {"ok": False, "error": "trade_type must be scalping or intraday"}
    profile = _profile_config(normalized_trade_type)
    limit = max(260, min(int(candle_limit or 1000), 3000))
    offset = max(0, min(int(candle_offset or 0), 5000))
    risk_usdt = max(float(risk_amount or 20.0), 1.0)
    fee_rate = max(float(fee_bps or 0.0), 0.0) / 10_000
    hold_limit = max(5, min(int(max_hold_candles or profile["max_hold_candles"]), 2000))

    trigger_fetch_limit = min(5000, limit + offset)
    ok_trigger, trigger_raw, trigger_error = client.safe_fetch_recent_candles(
        normalized_symbol,
        interval=profile["trigger_interval"],
        limit=trigger_fetch_limit,
    )
    if not ok_trigger:
        return {"ok": False, "error": trigger_error or f"{profile['trigger_interval']}m candles unavailable"}
    candles_trigger = _window_with_offset(trigger_raw, limit=limit, offset=offset)

    setup_limit = max(260, min(3000, (limit // profile["setup_ratio"]) + offset + 260))
    ok_setup, candles_setup, setup_error = client.safe_fetch_recent_candles(
        normalized_symbol,
        interval=profile["setup_interval"],
        limit=setup_limit,
    )
    if not ok_setup:
        return {"ok": False, "error": setup_error or f"{profile['setup_interval']}m candles unavailable"}

    trend_count = 0
    if profile["trend_interval"]:
        ok_trend, candles_trend, _trend_error = client.safe_fetch_recent_candles(
            normalized_symbol,
            interval=profile["trend_interval"],
            limit=max(260, min(1000, (limit // profile["trend_ratio"]) + offset + 260)),
        )
        trend_count = len(candles_trend) if ok_trend else 0

    if len(candles_trigger) < 80 or len(candles_setup) < 220:
        return {
            "ok": False,
            "error": "Not enough candle history for strategy warm-up",
            "candles_trigger": len(candles_trigger),
            "candles_setup": len(candles_setup),
        }

    trades: list[dict[str, Any]] = []
    equity_curve = [0.0]
    skipped_signals = 0
    last_signal_key: str | None = None
    index = 40
    while index < len(candles_trigger) - 2:
        now = _timestamp(candles_trigger[index])
        if now is None:
            index += 1
            continue
        window_setup = [candle for candle in candles_setup if (_timestamp(candle) or now) <= now]
        if len(window_setup) < 220:
            index += 1
            continue

        signal = _evaluate(normalized_strategy, normalized_symbol, window_setup, candles_trigger[: index + 1], now)
        if str(signal.get("status") or "").lower() != "active":
            index += 1
            continue
        if float(signal.get("risk_reward") or 0.0) + 1e-9 < min_risk_reward:
            skipped_signals += 1
            index += 1
            continue

        signal_key = "|".join(
            [
                str(signal.get("strategy_name") or signal.get("strategy") or normalized_strategy),
                str(signal.get("direction") or ""),
                str(signal.get("detected_at") or ""),
                str(signal.get("entry") or ""),
            ]
        )
        if signal_key == last_signal_key:
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
        "candles_1m": len(candles_trigger) if profile["trigger_interval"] == "1" else 0,
        "candles_5m": len(candles_trigger) if profile["trigger_interval"] == "5" else len(candles_setup) if profile["setup_interval"] == "5" else 0,
        "candles_trigger": len(candles_trigger),
        "candles_setup": len(candles_setup),
        "candles_trend": trend_count,
        "candle_offset": offset,
        "risk_amount": risk_usdt,
        "fee_bps": fee_bps,
        "min_risk_reward": min_risk_reward,
        "max_hold_candles": hold_limit,
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
        },
        "trades": trades[-100:],
        "equity_curve": equity_curve[-300:],
    }


def _evaluate(
    strategy: str,
    symbol: str,
    candles_5m: list[dict[str, Any]],
    candles_1m: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    if strategy == "all":
        return evaluate_strategy_pipeline(symbol, candles_5m, candles_1m, now)
    definition = get_strategy_registry().get(strategy)
    if definition is None:
        return {"status": "rejected", "rejection_reason": "unknown_strategy"}
    return definition.evaluator(symbol, candles_5m, candles_1m, now)


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
        }
    return None


def _profile_config(trade_type: str) -> dict[str, Any]:
    if trade_type == "intraday":
        return {
            "trade_type": "intraday",
            "label": "Intraday",
            "trend_interval": "60",
            "setup_interval": "15",
            "trigger_interval": "5",
            "setup_ratio": 3,
            "trend_ratio": 12,
            "default_risk_amount": 50.0,
            "default_min_risk_reward": 2.0,
            "max_hold_candles": 72,
        }
    return {
        "trade_type": "scalping",
        "label": "Scalping",
        "trend_interval": None,
        "setup_interval": "5",
        "trigger_interval": "1",
        "setup_ratio": 5,
        "trend_ratio": 60,
        "default_risk_amount": 20.0,
        "default_min_risk_reward": 1.5,
        "max_hold_candles": 240,
    }


def _window_with_offset(candles: list[dict[str, Any]], *, limit: int, offset: int) -> list[dict[str, Any]]:
    if offset <= 0:
        return candles[-limit:]
    end = max(len(candles) - offset, 0)
    start = max(end - limit, 0)
    return candles[start:end]


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

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Any

from app.bot_controls import can_execute, get_execution_mode
from app.exchange import BybitClient, ExchangeError
from app.journal import append_trade_event, create_trade_entry, log_bot_event, update_trade_entry
from app.position_sizing import calculate_position_size
from app.risk import register_active_trade, start_loss_cooldown, validate_trade


SL_REASON_UNKNOWN = "unknown"
SL_REASON_EXCHANGE_CLOSE = "exchange_close"
SL_REASON_FORCED_RISK_CLOSE = "forced_risk_close"
RESULT_PROTECTION_FAILED = "protection_failed"

_execution_lock = Lock()
_active_trades: list[dict[str, Any]] = []
_closed_trades: list[dict[str, Any]] = []
_active_order_ids: list[str] = []


def execute_signal(client: BybitClient, signal: dict[str, Any], auto_triggered: bool = False) -> dict[str, Any]:
    allowed, reason = can_execute()
    if not allowed:
        return {"ok": False, "error": reason}

    validation = validate_trade(signal)
    if not validation.get("allowed"):
        return {"ok": False, "error": validation.get("reason", "Risk validation failed")}

    normalized_signal = _normalize_signal(signal)
    if normalized_signal is None:
        return {"ok": False, "error": "Invalid execution signal payload"}

    ok_symbol, symbol_infos, symbol_error = client.safe_fetch_symbol_info(symbol=normalized_signal["symbol"])
    if not ok_symbol or not symbol_infos:
        return {"ok": False, "error": symbol_error or "Symbol info unavailable"}

    ok_wallet, wallet, wallet_error = client.safe_fetch_wallet_balance()
    if not ok_wallet or wallet is None:
        return {"ok": False, "error": wallet_error or "Wallet balance unavailable"}

    ok_positions, positions, positions_error = client.safe_fetch_positions()
    if not ok_positions:
        return {"ok": False, "error": positions_error or "Position data unavailable"}

    symbol_info = symbol_infos[0]
    sizing = calculate_position_size(
        signal=normalized_signal,
        wallet=wallet,
        symbol_info=symbol_info,
        active_trades=get_active_trades(),
        positions=positions,
        settings={
            "risk_per_trade": float(validation.get("risk_per_trade", 0.01)),
            "leverage_cap": validation.get("leverage_cap"),
            "exposure_cap": validation.get("exposure_cap"),
        },
        client=client,
    )
    if not sizing.get("allowed"):
        return {"ok": False, "error": sizing.get("reason", "Unsafe position sizing rejected"), "sizing": sizing}

    quantity = str(sizing["quantity"])
    stop_loss = client.normalize_price(normalized_signal["stop_loss"], symbol_info["tickSize"])
    side = "Buy" if normalized_signal["direction"] == "long" else "Sell"
    execution_mode = get_execution_mode()

    try:
        order_result = client.place_market_order(symbol=normalized_signal["symbol"], side=side, qty=quantity)
    except ExchangeError as exc:
        return {"ok": False, "error": str(exc)}

    order_id = str(order_result.get("orderId") or order_result.get("orderLinkId") or "")
    management = _build_management_state(
        entry=normalized_signal["entry"],
        stop_loss=float(stop_loss),
        take_profit=normalized_signal["take_profit"],
        quantity=quantity,
        direction=normalized_signal["direction"],
    )
    take_profit = client.normalize_price(management["runner_target"], symbol_info["tickSize"])

    trade = {
        "symbol": normalized_signal["symbol"],
        "direction": normalized_signal["direction"],
        "entry": normalized_signal["entry"],
        "stop_loss": float(stop_loss),
        "take_profit": normalized_signal["take_profit"],
        "quantity": quantity,
        "order_id": order_id,
        "status": "active",
        "detected_at": normalized_signal.get("detected_at"),
        "opened_at": _utc_now_iso(),
        "execution_mode": execution_mode,
        "result": None,
        "sl_hit_reason": None,
        "remaining_quantity": quantity,
        "management": management,
        "auto_triggered": auto_triggered,
        "exchange_metadata": {
            "mode": execution_mode,
            "order_response": order_result,
            "position_sizing": sizing,
            "management": management,
        },
    }

    journal = create_trade_entry(trade)
    trade["journal_id"] = journal["journal_id"]

    protection_error = _attach_protection_with_retry(
        client=client,
        symbol=normalized_signal["symbol"],
        take_profit=take_profit,
        stop_loss=stop_loss,
        journal_id=journal["journal_id"],
    )
    if protection_error:
        close_side = "Sell" if normalized_signal["direction"] == "long" else "Buy"
        close_error: str | None = None
        close_result: dict[str, Any] = {}
        try:
            close_result = client.close_position_market(symbol=normalized_signal["symbol"], side=close_side, qty=quantity)
        except ExchangeError as exc:
            close_error = str(exc)

        trade.update(
            {
                "status": "closed",
                "result": RESULT_PROTECTION_FAILED,
                "close_reason": "PROTECTION_FAILED",
                "closed_at": _utc_now_iso(),
                "exchange_metadata": {
                    **trade["exchange_metadata"],
                    "protection_error": protection_error,
                    "emergency_close_response": close_result,
                    "emergency_close_error": close_error,
                },
            }
        )
        update_trade_entry(
            journal["journal_id"],
            {
                "status": "closed",
                "result": RESULT_PROTECTION_FAILED,
                "closed_at": trade["closed_at"],
                "exchange_metadata": trade["exchange_metadata"],
            },
        )
        append_trade_event(
            journal["journal_id"],
            "PROTECTION_FAILED",
            "Protection failed twice; position was closed immediately.",
            {"symbol": normalized_signal["symbol"], "error": protection_error, "close_error": close_error},
        )
        log_bot_event(
            "PROTECTION_FAILED",
            f"Protection failed for {normalized_signal['symbol']}; immediate close requested.",
            level="error",
            metadata={
                "endpoint": "/execute",
                "affected_module": "execution",
                "error_code": "PROTECTION_FAILED",
                "symbol": normalized_signal["symbol"],
                "error": protection_error,
                "close_error": close_error,
            },
        )
        with _execution_lock:
            _closed_trades.append(trade)
        return {"ok": False, "error": "PROTECTION_FAILED", "trade": trade, "sizing": sizing}

    with _execution_lock:
        _active_trades.append(trade)
        if order_id:
            _active_order_ids.append(order_id)

    register_active_trade(normalized_signal["symbol"])
    return {"ok": True, "trade": trade, "sizing": sizing, "warning": None}


def get_active_trades() -> list[dict[str, Any]]:
    with _execution_lock:
        return [dict(trade) for trade in _active_trades]


def get_closed_trades() -> list[dict[str, Any]]:
    with _execution_lock:
        return [dict(trade) for trade in _closed_trades]


def replace_active_trades(trades: list[dict[str, Any]]) -> None:
    with _execution_lock:
        _active_trades.clear()
        _active_trades.extend(dict(trade) for trade in trades)
        _active_order_ids.clear()
        _active_order_ids.extend(str(trade.get("order_id")) for trade in trades if trade.get("order_id"))


def update_active_trade(journal_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    with _execution_lock:
        trade = next((item for item in _active_trades if item.get("journal_id") == journal_id), None)
        if trade is None:
            return None
        trade.update(updates)
        return dict(trade)


def close_trade(journal_id: str, close_fields: dict[str, Any]) -> dict[str, Any] | None:
    with _execution_lock:
        trade = next((item for item in _active_trades if item.get("journal_id") == journal_id), None)
        if trade is None:
            return None

        closed_trade = dict(trade)
        closed_trade.update(close_fields)
        closed_trade["status"] = "closed"
        closed_trade["closed_at"] = close_fields.get("closed_at") or _utc_now_iso()
        _active_trades[:] = [item for item in _active_trades if item.get("journal_id") != journal_id]
        _closed_trades.append(closed_trade)
        if closed_trade.get("order_id"):
            _active_order_ids[:] = [item for item in _active_order_ids if item != closed_trade.get("order_id")]

    update_trade_entry(
        journal_id,
        {
            "status": "closed",
            "result": closed_trade.get("result"),
            "sl_hit_reason": closed_trade.get("sl_hit_reason"),
            "closed_at": closed_trade.get("closed_at"),
            "exchange_metadata": closed_trade.get("exchange_metadata"),
        },
    )
    if closed_trade.get("result") == "sl":
        start_loss_cooldown()
    return closed_trade


def add_closed_trades(trades: list[dict[str, Any]]) -> None:
    if not trades:
        return
    with _execution_lock:
        for trade in trades:
            _closed_trades.append(dict(trade))


def _normalize_signal(signal: dict[str, Any]) -> dict[str, Any] | None:
    try:
        direction = str(signal.get("direction", "")).lower()
        if direction not in {"long", "short"}:
            return None
        return {
            "symbol": str(signal.get("symbol", "")).upper(),
            "direction": direction,
            "entry": float(signal.get("entry")),
            "stop_loss": float(signal.get("stop_loss")),
            "take_profit": float(signal.get("take_profit")),
            "detected_at": signal.get("detected_at"),
        }
    except (TypeError, ValueError):
        return None


def _attach_protection_with_retry(*, client: BybitClient, symbol: str, take_profit: str, stop_loss: str, journal_id: str) -> str | None:
    last_error: str | None = None
    for attempt in (1, 2):
        try:
            client.set_trading_stop(symbol=symbol, take_profit=take_profit, stop_loss=stop_loss)
            append_trade_event(
                journal_id,
                "PROTECTION_ATTACHED",
                "Initial SL/TP protection attached.",
                {"symbol": symbol, "attempt": attempt, "take_profit": take_profit, "stop_loss": stop_loss},
            )
            return None
        except ExchangeError as exc:
            last_error = str(exc)
            append_trade_event(
                journal_id,
                "PROTECTION_RETRY" if attempt == 1 else "PROTECTION_FAILED",
                "Protection attach failed.",
                {"symbol": symbol, "attempt": attempt, "error": last_error},
            )
    return last_error


def _build_management_state(entry: float, stop_loss: float, take_profit: float, quantity: str, direction: str) -> dict[str, Any]:
    """Build the confirmed 1:2, 1:2.5 and 1:3 management targets."""
    risk = abs(entry - stop_loss)
    qty_value = _to_float(quantity, 0.0)

    if direction == "long":
        tp1 = entry + risk * 2.0
        tp2 = entry + risk * 2.5
        runner_target = entry + risk * 3.0
    else:
        tp1 = entry - risk * 2.0
        tp2 = entry - risk * 2.5
        runner_target = entry - risk * 3.0

    return {
        "tp1": tp1,
        "tp2": tp2,
        "strategy_take_profit": take_profit,
        "runner_target": runner_target,
        "tp1_fraction": 0.5,
        "tp2_fraction": 0.25,
        "runner_fraction": 0.25,
        "initial_quantity": qty_value,
        "remaining_quantity": qty_value,
        "tp1_done": False,
        "tp2_done": False,
        "break_even_set": False,
        "trailing_stop": None,
        "last_momentum_check": None,
        "last_state_change": _utc_now_iso(),
    }


def _to_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()

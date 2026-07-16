from __future__ import annotations

import json
from datetime import UTC, datetime
from math import isfinite
from typing import Any

from app.authoritative_state import get_snapshot, publish_runtime_fields
from app.database import SessionLocal
from app.execution import get_operator_active_trades
from app.journal import get_trade_history, log_bot_event
from app.ledger_audit import get_account_ledger_audit
from app.models import WatchdogRuntimeState
from app.runtime_guard import set_watchdog_execution_block

DEFAULT_WATCHDOG_CONFIG = {
    "enabled": True,
    "interval_seconds": 30,
    "action_mode": "safe_stop",
    "mismatch_tolerance_cycles": 1,
    "exposure_tolerance_ratio": 0.01,
    "pnl_tolerance": 0.10,
}

VALID_ACTION_MODES = {"monitor", "reconcile", "safe_stop"}
CRITICAL_CODES = {
    "EXCHANGE_POSITION_FETCH_FAILED",
    "EXCHANGE_WALLET_FETCH_FAILED",
    "POSITION_SET_MISMATCH",
    "MISSING_NATIVE_PROTECTION",
}


def ensure_watchdog_state() -> dict[str, Any]:
    db = SessionLocal()
    try:
        row = db.query(WatchdogRuntimeState).filter(WatchdogRuntimeState.id == 1).first()
        if row is None:
            row = WatchdogRuntimeState(id=1, **DEFAULT_WATCHDOG_CONFIG)
            db.add(row)
            db.commit()
            db.refresh(row)
        return _serialize(row)
    finally:
        db.close()


def update_watchdog_config(
    *,
    enabled: bool | None = None,
    interval_seconds: int | None = None,
    action_mode: str | None = None,
    mismatch_tolerance_cycles: int | None = None,
    exposure_tolerance_ratio: float | None = None,
    pnl_tolerance: float | None = None,
) -> dict[str, Any]:
    ensure_watchdog_state()
    db = SessionLocal()
    try:
        row = db.query(WatchdogRuntimeState).filter(WatchdogRuntimeState.id == 1).first()
        if row is None:
            raise RuntimeError("Watchdog runtime state is unavailable")
        if enabled is not None:
            row.enabled = bool(enabled)
        if interval_seconds is not None:
            if int(interval_seconds) < 10 or int(interval_seconds) > 300:
                raise ValueError("Watchdog interval must be between 10 and 300 seconds")
            row.interval_seconds = int(interval_seconds)
        if action_mode is not None:
            normalized = str(action_mode).lower().strip()
            if normalized not in VALID_ACTION_MODES:
                raise ValueError("Watchdog action mode must be monitor, reconcile or safe_stop")
            row.action_mode = normalized
        if mismatch_tolerance_cycles is not None:
            if int(mismatch_tolerance_cycles) < 1 or int(mismatch_tolerance_cycles) > 10:
                raise ValueError("Mismatch tolerance cycles must be between 1 and 10")
            row.mismatch_tolerance_cycles = int(mismatch_tolerance_cycles)
        if exposure_tolerance_ratio is not None:
            value = float(exposure_tolerance_ratio)
            if value < 0 or value > 0.10:
                raise ValueError("Exposure tolerance ratio must be between 0 and 0.10")
            row.exposure_tolerance_ratio = value
        if pnl_tolerance is not None:
            value = float(pnl_tolerance)
            if value < 0 or value > 100:
                raise ValueError("PnL tolerance must be between 0 and 100 USDT")
            row.pnl_tolerance = value
        db.commit()
        db.refresh(row)
        return _serialize(row)
    finally:
        db.close()


def run_watchdog_cycle(client: Any, *, reconciliation_result: dict[str, Any] | None = None) -> dict[str, Any]:
    config = ensure_watchdog_state()
    if not config["enabled"]:
        set_watchdog_execution_block(False, "", status="DISABLED")
        return _persist_result(
            config,
            status="DISABLED",
            execution_blocked=False,
            reasons=[],
            snapshot=get_snapshot(),
        )

    reasons: list[dict[str, Any]] = []
    wallet_ok, wallet, wallet_error = client.safe_fetch_wallet_balance()
    positions_ok, positions, positions_error = client.safe_fetch_positions()
    orders_ok, open_orders, orders_error = client.safe_fetch_open_orders()

    if not wallet_ok:
        reasons.append(_reason("EXCHANGE_WALLET_FETCH_FAILED", wallet_error or "Wallet fetch failed", True))
    if not positions_ok:
        reasons.append(_reason("EXCHANGE_POSITION_FETCH_FAILED", positions_error or "Position fetch failed", True))
    if not orders_ok:
        reasons.append(_reason("OPEN_ORDER_FETCH_FAILED", orders_error or "Open-order fetch failed", False))

    active_positions = [item for item in (positions or []) if _position_open(item)] if positions_ok else []
    exchange_symbols = sorted({str(item.get("symbol") or "").upper() for item in active_positions if item.get("symbol")})
    app_trades = get_operator_active_trades()
    app_symbols = sorted({str(item.get("symbol") or "").upper() for item in app_trades if item.get("symbol")})

    if positions_ok and exchange_symbols != app_symbols:
        reasons.append(
            _reason(
                "POSITION_SET_MISMATCH",
                f"Exchange symbols {exchange_symbols} differ from app symbols {app_symbols}",
                True,
                exchange_symbols=exchange_symbols,
                app_symbols=app_symbols,
            )
        )

    missing_protection = [
        str(item.get("symbol") or "").upper()
        for item in active_positions
        if not _positive(item.get("stopLoss")) or not _positive(item.get("takeProfit"))
    ]
    if missing_protection:
        reasons.append(
            _reason(
                "MISSING_NATIVE_PROTECTION",
                f"Native stop-loss/take-profit missing for {sorted(missing_protection)}",
                True,
                symbols=sorted(missing_protection),
            )
        )

    exchange_exposure = sum(_position_notional(item) for item in active_positions)
    app_exposure = sum(_trade_notional(item) for item in app_trades)
    exposure_gap = abs(exchange_exposure - app_exposure)
    exposure_denominator = max(abs(exchange_exposure), 1.0)
    exposure_gap_ratio = exposure_gap / exposure_denominator
    if positions_ok and exposure_gap_ratio > float(config["exposure_tolerance_ratio"]):
        reasons.append(
            _reason(
                "EXPOSURE_MISMATCH",
                f"Exposure gap {exposure_gap:.8f} exceeds tolerance",
                False,
                exchange_exposure=exchange_exposure,
                app_exposure=app_exposure,
                gap_ratio=exposure_gap_ratio,
            )
        )

    ledger = {"ok": False, "summary": {}, "error": "Ledger unavailable"}
    if wallet_ok:
        try:
            ledger = get_account_ledger_audit(client)
        except Exception as exc:
            ledger = {"ok": False, "summary": {}, "error": str(exc)}
    if not ledger.get("ok"):
        reasons.append(_reason("LEDGER_AUDIT_UNAVAILABLE", str(ledger.get("error") or "Ledger unavailable"), False))

    wallet_data = wallet if isinstance(wallet, dict) else {}
    ledger_summary = ledger.get("summary") if isinstance(ledger.get("summary"), dict) else {}
    runtime_fields = {
        "captured_at": datetime.now(UTC).isoformat(),
        "wallet": wallet_data,
        "positions": active_positions,
        "open_orders": open_orders or [],
        "exchange_position_count": len(active_positions),
        "app_position_count": len(app_trades),
        "exchange_exposure": exchange_exposure,
        "app_exposure": app_exposure,
        "exposure_gap": exposure_gap,
        "account_net": _number(ledger_summary.get("net_change")),
        "trade_net": _number(ledger_summary.get("trade_change")),
        "fees": abs(_number(ledger_summary.get("fees")) or 0.0),
        "funding": _number(ledger_summary.get("funding")) or 0.0,
        "ledger_status": "authoritative" if ledger.get("ok") else "unavailable",
        "ledger_error": ledger.get("error"),
        "reconciliation_ok": bool((reconciliation_result or {}).get("ok", True)),
    }
    snapshot = publish_runtime_fields(runtime_fields, source="runtime_watchdog")

    critical = any(bool(item.get("critical")) for item in reasons)
    previous_mismatch = int(config.get("consecutive_mismatch_cycles") or 0)
    mismatch_cycles = previous_mismatch + 1 if reasons else 0
    tolerance_reached = mismatch_cycles >= int(config["mismatch_tolerance_cycles"])
    execution_blocked = bool(
        config["action_mode"] == "safe_stop" and critical and tolerance_reached
    )
    status = _status(reasons, execution_blocked)
    block_reason = "; ".join(str(item["code"]) for item in reasons if item.get("critical"))
    set_watchdog_execution_block(execution_blocked, block_reason, status=status)

    result = _persist_result(
        config,
        status=status,
        execution_blocked=execution_blocked,
        reasons=reasons,
        snapshot=snapshot,
        consecutive_mismatch_cycles=mismatch_cycles,
    )
    _log_state_transition(config, result)
    return result


def get_watchdog_runtime_status() -> dict[str, Any]:
    state = ensure_watchdog_state()
    state["snapshot"] = get_snapshot()
    return state


def get_watchdog_incidents(limit: int = 100) -> list[dict[str, Any]]:
    return [
        item
        for item in get_trade_history(limit=1)[:0]
    ] or [
        event
        for event in __import__("app.journal", fromlist=["get_bot_events"]).get_bot_events(limit)
        if str(event.get("event_type") or "").startswith("watchdog_")
    ]


def _persist_result(
    config: dict[str, Any],
    *,
    status: str,
    execution_blocked: bool,
    reasons: list[dict[str, Any]],
    snapshot: dict[str, Any],
    consecutive_mismatch_cycles: int | None = None,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        row = db.query(WatchdogRuntimeState).filter(WatchdogRuntimeState.id == 1).first()
        if row is None:
            row = WatchdogRuntimeState(id=1, **DEFAULT_WATCHDOG_CONFIG)
            db.add(row)
            db.flush()
        row.status = status
        row.execution_blocked = bool(execution_blocked)
        row.reasons_json = json.dumps(reasons, separators=(",", ":"))
        row.last_checked_at = datetime.now(UTC)
        row.last_snapshot_version = int(snapshot.get("version") or 0)
        row.consecutive_mismatch_cycles = int(
            consecutive_mismatch_cycles
            if consecutive_mismatch_cycles is not None
            else row.consecutive_mismatch_cycles or 0
        )
        db.commit()
        db.refresh(row)
        result = _serialize(row)
        result["reasons"] = reasons
        result["snapshot"] = snapshot
        return result
    finally:
        db.close()


def _serialize(row: WatchdogRuntimeState) -> dict[str, Any]:
    try:
        reasons = json.loads(row.reasons_json or "[]")
    except json.JSONDecodeError:
        reasons = []
    return {
        "enabled": bool(row.enabled),
        "interval_seconds": int(row.interval_seconds),
        "action_mode": str(row.action_mode),
        "mismatch_tolerance_cycles": int(row.mismatch_tolerance_cycles),
        "exposure_tolerance_ratio": float(row.exposure_tolerance_ratio),
        "pnl_tolerance": float(row.pnl_tolerance),
        "status": str(row.status),
        "execution_blocked": bool(row.execution_blocked),
        "reasons": reasons,
        "consecutive_mismatch_cycles": int(row.consecutive_mismatch_cycles),
        "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else None,
        "last_snapshot_version": int(row.last_snapshot_version or 0),
    }


def _log_state_transition(previous: dict[str, Any], current: dict[str, Any]) -> None:
    previous_status = str(previous.get("status") or "UNINITIALIZED")
    current_status = str(current.get("status") or "UNINITIALIZED")
    if previous_status == current_status:
        return
    level = "warning" if current_status in {"EXECUTION_BLOCKED", "CRITICAL"} else "info"
    log_bot_event(
        "watchdog_state_changed",
        f"Runtime watchdog changed from {previous_status} to {current_status}",
        level=level,
        metadata={
            "affected_module": "watchdog",
            "error_code": current_status,
            "previous_status": previous_status,
            "current_status": current_status,
            "reasons": current.get("reasons") or [],
        },
    )


def _status(reasons: list[dict[str, Any]], execution_blocked: bool) -> str:
    if execution_blocked:
        return "EXECUTION_BLOCKED"
    if any(item.get("critical") for item in reasons):
        return "CRITICAL"
    if reasons:
        return "RECONCILING"
    return "HEALTHY"


def _reason(code: str, message: str, critical: bool, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "critical": critical, "evidence": evidence}


def _position_open(position: dict[str, Any]) -> bool:
    return (_number(position.get("size")) or 0.0) > 0


def _position_notional(position: dict[str, Any]) -> float:
    size = abs(_number(position.get("size")) or 0.0)
    price = _number(position.get("markPrice")) or _number(position.get("avgPrice")) or 0.0
    return size * price


def _trade_notional(trade: dict[str, Any]) -> float:
    quantity = abs(_number(trade.get("remaining_quantity")) or _number(trade.get("quantity")) or 0.0)
    price = _number(trade.get("mark_price")) or _number(trade.get("entry")) or 0.0
    return quantity * price


def _positive(value: Any) -> bool:
    return (_number(value) or 0.0) > 0


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None

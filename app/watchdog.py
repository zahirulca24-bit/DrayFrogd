from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.auth import is_auth_configured
from app.bot_controls import can_execute, get_execution_mode
from app.config import settings
from app.database import SessionLocal
from app.execution import get_active_trades
from app.exchange import get_exchange_client
from app.journal import get_bot_events, get_trade_history
from app.readiness import get_readiness_status
from app.risk import get_risk_state
from app.scanner import get_active_signals, get_latest_signals


def get_watchdog_snapshot(worker_running: bool) -> dict[str, Any]:
    readiness = get_readiness_status()
    mode = get_execution_mode()
    selected_exchange = get_exchange_client(mode).get_status()
    risk_state = get_risk_state()
    execution_allowed, execution_reason = can_execute()
    scanner_results = get_latest_signals()
    active_signals = get_active_signals()
    active_trades = get_active_trades()
    trade_history = get_trade_history()
    bot_events = get_bot_events(100)

    modules = [
        _module_status(
            "backend",
            "ONLINE",
            "FastAPI health endpoint is responding.",
            "/health",
            "BACKEND_OK",
        ),
        _module_status(
            "bybit",
            "ONLINE" if selected_exchange.get("reachable") else "DEGRADED",
            selected_exchange.get("error") or "Exchange reachable.",
            "/exchange/status",
            "BYBIT_REACHABLE" if selected_exchange.get("reachable") else "BYBIT_UNREACHABLE",
        ),
        _module_status(
            "supabase",
            "ONLINE" if settings.supabase_url and settings.supabase_service_role_key else "NOT_CONFIGURED",
            "Supabase journaling credentials detected."
            if settings.supabase_url and settings.supabase_service_role_key
            else "Supabase credentials are missing.",
            "/journal/trades",
            "SUPABASE_READY" if settings.supabase_url and settings.supabase_service_role_key else "SUPABASE_MISSING",
        ),
        _module_status(
            "telegram",
            "NOT_CONFIGURED",
            "No backend Telegram integration detected.",
            None,
            "TELEGRAM_UNAVAILABLE",
        ),
        _module_status(
            "wallet",
            "ONLINE" if readiness["checks"]["wallet_fetch_success"] else "DEGRADED",
            readiness["errors"]["wallet"] or "Wallet fetch succeeded.",
            "/account",
            "WALLET_OK" if readiness["checks"]["wallet_fetch_success"] else "WALLET_FETCH_FAILED",
        ),
        _module_status(
            "scanner",
            "READY" if scanner_results else "IDLE",
            "Latest scanner results available in memory." if scanner_results else "No completed scanner results in memory yet.",
            "/scanner/results",
            "SCANNER_READY" if scanner_results else "SCANNER_IDLE",
        ),
        _module_status(
            "signal",
            "READY" if active_signals else "IDLE",
            f"{len(active_signals)} active signal(s) available." if active_signals else "No active signals available.",
            "/signals",
            "SIGNAL_ACTIVE" if active_signals else "SIGNAL_IDLE",
        ),
        _module_status(
            "risk",
            "BLOCKED" if risk_state.get("cooldown_until") else "READY",
            "Cooldown active after loss." if risk_state.get("cooldown_until") else "Risk engine ready for validation.",
            "/risk/state",
            "RISK_COOLDOWN" if risk_state.get("cooldown_until") else "RISK_READY",
        ),
        _module_status(
            "execution",
            "READY" if execution_allowed else "BLOCKED",
            execution_reason or "Execution pipeline ready.",
            "/execute",
            "EXECUTION_READY" if execution_allowed else "EXECUTION_BLOCKED",
        ),
        _module_status(
            "journal",
            "ONLINE" if trade_history is not None else "DEGRADED",
            f"{len(trade_history)} journal record(s) available." if trade_history is not None else "Journal query failed.",
            "/journal/trades",
            "JOURNAL_READY" if trade_history is not None else "JOURNAL_FAILED",
        ),
        _module_status(
            "database",
            "ONLINE" if _database_ok() else "OFFLINE",
            "Database connection check succeeded." if _database_ok() else "Database connection check failed.",
            None,
            "DATABASE_OK" if _database_ok() else "DATABASE_OFFLINE",
        ),
        _module_status(
            "worker",
            "ONLINE" if worker_running else "OFFLINE",
            "Background worker loop is running." if worker_running else "Background worker loop is not running.",
            None,
            "WORKER_RUNNING" if worker_running else "WORKER_STOPPED",
        ),
    ]

    incidents = [_to_incident(item) for item in bot_events if item.get("level") in {"warning", "error"}]
    open_incidents = [
        item for item in incidents if item["affected_module"] in {module["module"] for module in modules if module["status"] in {"DEGRADED", "OFFLINE", "BLOCKED"}}
    ]

    return {
        "generated_at": _now_iso(),
        "mode": mode,
        "admin_auth_configured": is_auth_configured(),
        "modules": modules,
        "incidents": incidents,
        "summary": {
            "overall_status": "HEALTHY" if all(module["status"] in {"ONLINE", "READY", "IDLE", "NOT_CONFIGURED"} for module in modules) else "DEGRADED",
            "open_incidents": len(open_incidents),
            "total_incidents": len(incidents),
            "affected_modules": sorted({item["affected_module"] for item in open_incidents}),
        },
    }


def _to_incident(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata") or {}
    endpoint = metadata.get("endpoint")
    affected_module = str(metadata.get("affected_module") or _infer_module(event.get("event_type", "")))
    return {
        "id": event.get("id"),
        "timestamp": event.get("created_at"),
        "error_code": str(metadata.get("error_code") or str(event.get("event_type", "incident")).upper()),
        "endpoint": endpoint,
        "retry_count": int(metadata.get("retry_count") or 0),
        "affected_module": affected_module,
        "level": event.get("level"),
        "message": event.get("message"),
        "technical_evidence": metadata.get("error") or metadata.get("result") or event.get("message"),
        "recovery_status": "Recovered" if affected_module not in {"backend", "bybit", "wallet", "database"} else "Monitoring",
        "root_cause": metadata.get("root_cause") or metadata.get("error") or "Cause Not Confirmed",
    }


def _infer_module(event_type: str) -> str:
    normalized = event_type.lower()
    if "scan" in normalized:
        return "scanner"
    if "trade" in normalized or "execution" in normalized:
        return "execution"
    if "loop" in normalized or "worker" in normalized:
        return "worker"
    if "bot" in normalized:
        return "backend"
    return "backend"


def _module_status(module: str, status: str, reason: str, endpoint: str | None, code: str) -> dict[str, Any]:
    return {
        "module": module,
        "status": status,
        "reason": reason,
        "endpoint": endpoint,
        "error_code": code,
    }


def _database_ok() -> bool:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        db.close()


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()

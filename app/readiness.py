from typing import Any

from app.auth import is_auth_configured
from app.bot_controls import get_execution_mode, is_live_mode_available
from app.config import settings
from app.database import DATABASE_URL
from app.exchange import BybitClient, get_exchange_client


def get_mode_readiness(client: BybitClient) -> dict[str, Any]:
    exchange_reachable, exchange_error = client.safe_ping()
    wallet_ok, _, wallet_error = client.safe_fetch_wallet_balance()
    api_keys_present = client.has_credentials()

    return {
        "mode": client.mode,
        "checks": {
            "api_keys_present": api_keys_present,
            "exchange_reachable": exchange_reachable,
            "wallet_fetch_success": wallet_ok,
        },
        "errors": {
            "exchange": exchange_error,
            "wallet": wallet_error,
        },
        "ready": all([api_keys_present, exchange_reachable, wallet_ok]),
    }


def get_readiness_status() -> dict[str, Any]:
    auth_configured = is_auth_configured()
    current_mode = get_execution_mode()
    demo = get_mode_readiness(get_exchange_client("demo"))
    live = get_mode_readiness(get_exchange_client("live"))
    selected = demo if current_mode == "demo" else live
    supabase_ready = bool(settings.supabase_url and settings.supabase_service_role_key)
    database_backend = "postgresql" if DATABASE_URL.startswith("postgresql+") else "sqlite"

    return {
        "mode": current_mode,
        "checks": {
            "admin_auth_configured": auth_configured,
            "api_keys_present": selected["checks"]["api_keys_present"],
            "exchange_reachable": selected["checks"]["exchange_reachable"],
            "wallet_fetch_success": selected["checks"]["wallet_fetch_success"],
        },
        "errors": selected["errors"],
        "persistence": {
            "local_journal_storage": {
                "configured": True,
                "backend": database_backend,
                "target": "trade_journal / bot_events",
            },
            "external_audit_sink": {
                "configured": supabase_ready,
                "provider": "supabase",
                "target": "trade_journal / bot_events",
                "status": "ready" if supabase_ready else "disabled",
            },
        },
        "ready_for_execution": auth_configured and selected["ready"],
        "demo": demo,
        "live": {
            **live,
            "live_mode_available": is_live_mode_available(),
        },
    }

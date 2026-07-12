from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends

from app.authoritative_reconciliation import reconcile_state
from app.authoritative_state import get_snapshot
from app.bot_controls import get_execution_mode
from app.bybit_websocket import websocket_service
from app.exchange import get_exchange_client

_installed = False


def install_runtime_integration() -> None:
    """Install read-only state and WebSocket status routes after app startup."""

    global _installed
    if _installed:
        return

    from app.main import app, require_authenticated

    for route in app.routes:
        path = getattr(route, "path", "")
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        if path == "/active-trades":
            _replace_route_call(route, authoritative_active_trades)
        elif path == "/reconcile":
            _replace_route_call(route, authoritative_reconcile)
        elif path == "/exchange/status":
            original = dependant.call

            def exchange_status_with_websocket(_original: Callable[..., dict[str, Any]] = original) -> dict[str, Any]:
                payload = dict(_original())
                payload["websocket"] = websocket_service.get_status()
                return payload

            _replace_route_call(route, exchange_status_with_websocket)

    if not any(getattr(route, "path", "") == "/websocket/status" for route in app.routes):
        app.add_api_route(
            "/websocket/status",
            websocket_status,
            methods=["GET"],
            dependencies=[Depends(require_authenticated)],
            tags=["exchange"],
        )
    app.openapi_schema = None
    _installed = True


def authoritative_active_trades(_: dict | None = None) -> dict[str, Any]:
    snapshot = get_snapshot()
    return {
        "trades": list(snapshot.get("trades") or []),
        "positions_synced": bool(snapshot.get("positions_synced")),
        "error": (snapshot.get("errors") or [None])[0],
        "snapshot_version": snapshot.get("version"),
        "snapshot_source": snapshot.get("source"),
        "updated_at": snapshot.get("updated_at"),
    }


def authoritative_reconcile(_: dict | None = None) -> dict[str, Any]:
    return reconcile_state(get_exchange_client(get_execution_mode()), source="manual_reconciliation")


def websocket_status() -> dict[str, Any]:
    return websocket_service.get_status()


def _replace_route_call(route: Any, call: Callable[..., Any]) -> None:
    route.endpoint = call
    route.dependant.call = call

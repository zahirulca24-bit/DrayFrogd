from __future__ import annotations

from app.authoritative_state import publish_snapshot, reset_snapshot
from app.main import app
from app.runtime_integration import install_runtime_integration


def test_runtime_integration_makes_active_trades_snapshot_read_only() -> None:
    reset_snapshot()
    publish_snapshot(
        [{"journal_id": "jrnl-1", "symbol": "BTCUSDT", "status": "active"}],
        mode="demo",
        source="test",
        positions_synced=True,
    )
    install_runtime_integration()
    route = next(item for item in app.routes if getattr(item, "path", "") == "/active-trades")
    payload = route.dependant.call(None)
    assert payload["positions_synced"] is True
    assert payload["snapshot_source"] == "test"
    assert payload["trades"][0]["symbol"] == "BTCUSDT"


def test_runtime_integration_registers_websocket_status_route_once() -> None:
    install_runtime_integration()
    install_runtime_integration()
    routes = [item for item in app.routes if getattr(item, "path", "") == "/websocket/status"]
    assert len(routes) == 1

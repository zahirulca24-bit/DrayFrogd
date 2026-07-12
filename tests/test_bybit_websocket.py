from __future__ import annotations

from app.authoritative_state import get_snapshot, publish_snapshot, reset_snapshot
from app.bybit_websocket import BybitWebSocketService


def test_private_execution_requests_reconciliation() -> None:
    service = BybitWebSocketService()
    service._private_callback(
        {"topic": "execution", "creationTime": 1, "data": [{"symbol": "BTCUSDT"}]}
    )
    status = service.get_status()
    assert status["private_event_counts"]["execution"] == 1
    assert service._last_reconcile_reason == "execution"


def test_public_ticker_updates_authoritative_snapshot() -> None:
    reset_snapshot()
    publish_snapshot(
        [{
            "journal_id": "jrnl-1",
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry": 100.0,
            "quantity": 2.0,
            "remaining_quantity": 2.0,
            "status": "active",
        }],
        mode="demo",
        source="test",
        positions_synced=True,
    )
    service = BybitWebSocketService()
    service._public_callback(
        {"topic": "tickers.BTCUSDT", "data": {"symbol": "BTCUSDT", "markPrice": "105"}}
    )
    trade = get_snapshot()["trades"][0]
    assert trade["mark_price"] == 105.0
    assert trade["unrealized_pnl"] == 10.0


def test_websocket_status_starts_stopped() -> None:
    status = BybitWebSocketService().get_status()
    assert status["running"] is False
    assert status["private"]["state"] == "stopped"
    assert status["public"]["state"] == "stopped"

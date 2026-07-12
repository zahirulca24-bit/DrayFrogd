from __future__ import annotations

import pytest

from app.authoritative_state import get_snapshot, publish_snapshot, reset_snapshot
from app.bybit_websocket import (
    BybitWebSocketService,
    _socket_is_authenticated,
    _socket_is_connected,
)


class FakeSocket:
    def __init__(self, *, connected: bool = True, authenticated: bool = True) -> None:
        self.connected = connected
        self.auth = authenticated
        self.endpoint = "wss://example.test/v5/private"
        self.closed = False
        self.subscriptions: list[str] = []

    def is_connected(self) -> bool:
        return self.connected and not self.closed

    def position_stream(self, callback) -> None:  # noqa: ANN001
        self.subscriptions.append("position")

    def order_stream(self, callback) -> None:  # noqa: ANN001
        self.subscriptions.append("order")

    def execution_stream(self, callback) -> None:  # noqa: ANN001
        self.subscriptions.append("execution")

    def wallet_stream(self, callback) -> None:  # noqa: ANN001
        self.subscriptions.append("wallet")

    def ticker_stream(self, symbol, callback) -> None:  # noqa: ANN001
        self.subscriptions.extend(f"tickers.{item}" for item in symbol)

    def orderbook_stream(self, depth, symbol, callback) -> None:  # noqa: ANN001
        self.subscriptions.append(f"orderbook.{depth}.{symbol}")

    def exit(self) -> None:
        self.closed = True
        self.connected = False


class FakeExchangeClient:
    api_key = "key"
    api_secret = "secret"

    @staticmethod
    def has_credentials() -> bool:
        return True


def test_private_execution_requests_reconciliation() -> None:
    service = BybitWebSocketService()
    service._private_ws = FakeSocket()
    service._private_callback(
        {"topic": "execution", "creationTime": 1, "data": [{"symbol": "BTCUSDT"}]}
    )
    status = service.get_status()
    assert status["private_event_counts"]["execution"] == 1
    assert status["private"]["last_message_at"] is not None
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
    service._public_ws = FakeSocket()
    service._public_callback(
        {"topic": "tickers.BTCUSDT", "data": {"symbol": "BTCUSDT", "markPrice": "105"}}
    )
    trade = get_snapshot()["trades"][0]
    assert trade["mark_price"] == 105.0
    assert trade["unrealized_pnl"] == 10.0
    assert service.get_status()["public"]["last_message_at"] is not None


def test_websocket_status_starts_stopped() -> None:
    status = BybitWebSocketService().get_status()
    assert status["running"] is False
    assert status["private"]["state"] == "stopped"
    assert status["public"]["state"] == "stopped"


def test_private_and_public_failures_are_isolated() -> None:
    service = BybitWebSocketService()
    service._set_channel("private", connected=True, authenticated=True, state="connected")
    service._set_channel("public", connected=True, state="connected")

    service._record_channel_failure("public", "ConnectionError: public failed", 2)
    status = service.get_status()
    assert status["private"]["state"] == "connected"
    assert status["private"]["connected"] is True
    assert status["public"]["state"] == "reconnecting"
    assert status["public"]["error"] == "ConnectionError: public failed"

    service._set_channel("public", connected=True, state="connected", error=None)
    service._record_channel_failure("private", "PermissionError: auth failed", 4)
    status = service.get_status()
    assert status["public"]["state"] == "connected"
    assert status["public"]["connected"] is True
    assert status["private"]["state"] == "reconnecting"
    assert status["private"]["error"] == "PermissionError: auth failed"


def test_socket_health_uses_pybit_connection_and_auth_flags() -> None:
    socket = FakeSocket(connected=True, authenticated=False)
    assert _socket_is_connected(socket) is True
    assert _socket_is_authenticated(socket) is False
    socket.auth = True
    assert _socket_is_authenticated(socket) is True
    socket.connected = False
    assert _socket_is_connected(socket) is False


def test_private_connection_requires_confirmed_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.bybit_websocket._safe_bot_event", lambda *args, **kwargs: None
    )
    socket = FakeSocket(connected=True, authenticated=False)
    monkeypatch.setattr(
        "app.bybit_websocket._pybit_websocket_class",
        lambda: lambda **kwargs: socket,
    )
    monkeypatch.setattr(
        "app.bybit_websocket.PRIVATE_AUTH_TIMEOUT_SECONDS", 0.01
    )

    service = BybitWebSocketService()
    with pytest.raises(PermissionError, match="authentication was not confirmed"):
        service._connect_private_client("demo", FakeExchangeClient())
    assert socket.closed is True
    assert service._private_ws is None


def test_private_connection_reports_connected_only_after_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.bybit_websocket._safe_bot_event", lambda *args, **kwargs: None
    )
    socket = FakeSocket(connected=True, authenticated=True)
    monkeypatch.setattr(
        "app.bybit_websocket._pybit_websocket_class",
        lambda: lambda **kwargs: socket,
    )

    service = BybitWebSocketService()
    service._connect_private_client("demo", FakeExchangeClient())
    status = service.get_status()["private"]
    assert status["connected"] is True
    assert status["authenticated"] is True
    assert status["state"] == "connected"
    assert status["topics"] == ["position", "order", "execution", "wallet"]
    assert socket.subscriptions == ["position", "order", "execution", "wallet"]


def test_public_connection_requires_confirmed_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.bybit_websocket._safe_bot_event", lambda *args, **kwargs: None
    )
    socket = FakeSocket(connected=False, authenticated=False)
    monkeypatch.setattr(
        "app.bybit_websocket._pybit_websocket_class",
        lambda: lambda **kwargs: socket,
    )
    monkeypatch.setattr("app.bybit_websocket.CONNECT_TIMEOUT_SECONDS", 0.01)

    service = BybitWebSocketService()
    with pytest.raises(TimeoutError, match="did not confirm socket connectivity"):
        service._connect_public_client({"BTCUSDT"})
    assert socket.closed is True
    assert service._public_ws is None


def test_public_connection_reports_connected_after_socket_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_snapshot()
    monkeypatch.setattr(
        "app.bybit_websocket._safe_bot_event", lambda *args, **kwargs: None
    )
    socket = FakeSocket(connected=True, authenticated=False)
    monkeypatch.setattr(
        "app.bybit_websocket._pybit_websocket_class",
        lambda: lambda **kwargs: socket,
    )

    service = BybitWebSocketService()
    service._connect_public_client({"BTCUSDT", "ETHUSDT"})
    status = service.get_status()["public"]
    assert status["connected"] is True
    assert status["state"] == "connected"
    assert status["topics"] == ["tickers.BTCUSDT", "tickers.ETHUSDT"]
    assert socket.subscriptions == ["tickers.BTCUSDT", "tickers.ETHUSDT"]

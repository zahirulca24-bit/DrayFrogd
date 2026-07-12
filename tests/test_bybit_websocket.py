from __future__ import annotations

import unittest
from unittest.mock import patch

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


class BybitWebSocketTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_snapshot()

    def test_private_execution_requests_reconciliation(self) -> None:
        service = BybitWebSocketService()
        service._private_ws = FakeSocket()
        service._private_callback(
            {
                "topic": "execution",
                "creationTime": 1,
                "data": [{"symbol": "BTCUSDT"}],
            }
        )
        status = service.get_status()
        self.assertEqual(status["private_event_counts"]["execution"], 1)
        self.assertIsNotNone(status["private"]["last_message_at"])
        self.assertEqual(service._last_reconcile_reason, "execution")

    def test_public_ticker_updates_authoritative_snapshot(self) -> None:
        reset_snapshot()
        publish_snapshot(
            [
                {
                    "journal_id": "jrnl-1",
                    "symbol": "BTCUSDT",
                    "direction": "long",
                    "entry": 100.0,
                    "quantity": 2.0,
                    "remaining_quantity": 2.0,
                    "status": "active",
                }
            ],
            mode="demo",
            source="test",
            positions_synced=True,
        )
        service = BybitWebSocketService()
        service._public_ws = FakeSocket()
        service._public_callback(
            {
                "topic": "tickers.BTCUSDT",
                "data": {"symbol": "BTCUSDT", "markPrice": "105"},
            }
        )
        trade = get_snapshot()["trades"][0]
        self.assertEqual(trade["mark_price"], 105.0)
        self.assertEqual(trade["unrealized_pnl"], 10.0)
        self.assertIsNotNone(service.get_status()["public"]["last_message_at"])

    def test_websocket_status_starts_stopped(self) -> None:
        status = BybitWebSocketService().get_status()
        self.assertFalse(status["running"])
        self.assertEqual(status["private"]["state"], "stopped")
        self.assertEqual(status["public"]["state"], "stopped")

    def test_private_and_public_failures_are_isolated(self) -> None:
        service = BybitWebSocketService()
        service._set_channel(
            "private", connected=True, authenticated=True, state="connected"
        )
        service._set_channel("public", connected=True, state="connected")

        service._record_channel_failure(
            "public", "ConnectionError: public failed", 2
        )
        status = service.get_status()
        self.assertEqual(status["private"]["state"], "connected")
        self.assertTrue(status["private"]["connected"])
        self.assertEqual(status["public"]["state"], "reconnecting")
        self.assertEqual(
            status["public"]["error"], "ConnectionError: public failed"
        )

        service._set_channel(
            "public", connected=True, state="connected", error=None
        )
        service._record_channel_failure(
            "private", "PermissionError: auth failed", 4
        )
        status = service.get_status()
        self.assertEqual(status["public"]["state"], "connected")
        self.assertTrue(status["public"]["connected"])
        self.assertEqual(status["private"]["state"], "reconnecting")
        self.assertEqual(
            status["private"]["error"], "PermissionError: auth failed"
        )

    def test_socket_health_uses_pybit_connection_and_auth_flags(self) -> None:
        socket = FakeSocket(connected=True, authenticated=False)
        self.assertTrue(_socket_is_connected(socket))
        self.assertFalse(_socket_is_authenticated(socket))
        socket.auth = True
        self.assertTrue(_socket_is_authenticated(socket))
        socket.connected = False
        self.assertFalse(_socket_is_connected(socket))

    def test_private_connection_requires_confirmed_authentication(self) -> None:
        socket = FakeSocket(connected=True, authenticated=False)
        with (
            patch("app.bybit_websocket._safe_bot_event"),
            patch(
                "app.bybit_websocket._pybit_websocket_class",
                return_value=lambda **kwargs: socket,
            ),
            patch("app.bybit_websocket.PRIVATE_AUTH_TIMEOUT_SECONDS", 0.01),
        ):
            service = BybitWebSocketService()
            with self.assertRaisesRegex(
                PermissionError, "authentication was not confirmed"
            ):
                service._connect_private_client("demo", FakeExchangeClient())
        self.assertTrue(socket.closed)
        self.assertIsNone(service._private_ws)

    def test_private_connection_reports_connected_only_after_auth(self) -> None:
        socket = FakeSocket(connected=True, authenticated=True)
        with (
            patch("app.bybit_websocket._safe_bot_event"),
            patch(
                "app.bybit_websocket._pybit_websocket_class",
                return_value=lambda **kwargs: socket,
            ),
        ):
            service = BybitWebSocketService()
            service._connect_private_client("demo", FakeExchangeClient())
        status = service.get_status()["private"]
        self.assertTrue(status["connected"])
        self.assertTrue(status["authenticated"])
        self.assertEqual(status["state"], "connected")
        self.assertEqual(
            status["topics"], ["position", "order", "execution", "wallet"]
        )
        self.assertEqual(
            socket.subscriptions, ["position", "order", "execution", "wallet"]
        )

    def test_public_connection_requires_confirmed_socket(self) -> None:
        socket = FakeSocket(connected=False, authenticated=False)
        with (
            patch("app.bybit_websocket._safe_bot_event"),
            patch(
                "app.bybit_websocket._pybit_websocket_class",
                return_value=lambda **kwargs: socket,
            ),
            patch("app.bybit_websocket.CONNECT_TIMEOUT_SECONDS", 0.01),
        ):
            service = BybitWebSocketService()
            with self.assertRaisesRegex(
                TimeoutError, "did not confirm socket connectivity"
            ):
                service._connect_public_client({"BTCUSDT"})
        self.assertTrue(socket.closed)
        self.assertIsNone(service._public_ws)

    def test_public_connection_reports_connected_after_socket_check(self) -> None:
        reset_snapshot()
        socket = FakeSocket(connected=True, authenticated=False)
        with (
            patch("app.bybit_websocket._safe_bot_event"),
            patch(
                "app.bybit_websocket._pybit_websocket_class",
                return_value=lambda **kwargs: socket,
            ),
        ):
            service = BybitWebSocketService()
            service._connect_public_client({"BTCUSDT", "ETHUSDT"})
        status = service.get_status()["public"]
        self.assertTrue(status["connected"])
        self.assertEqual(status["state"], "connected")
        self.assertEqual(
            status["topics"], ["tickers.BTCUSDT", "tickers.ETHUSDT"]
        )
        self.assertEqual(
            socket.subscriptions, ["tickers.BTCUSDT", "tickers.ETHUSDT"]
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.bybit_websocket import BybitWebSocketService


class FakeExchangeClient:
    pass


class BybitWebSocketPeriodicTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_timeout_runs_periodic_rest_reconciliation(self) -> None:
        service = BybitWebSocketService()
        service._stop = asyncio.Event()

        with (
            patch("app.bybit_websocket.RECONCILIATION_IDLE_SECONDS", 0.01),
            patch("app.bybit_websocket.get_execution_mode", return_value="demo"),
            patch(
                "app.bybit_websocket.get_exchange_client",
                return_value=FakeExchangeClient(),
            ),
            patch(
                "app.bybit_websocket.reconcile_state",
                return_value={"ok": True, "authoritative_trades": []},
            ) as reconcile_mock,
        ):
            task = asyncio.create_task(service._reconciliation_supervisor())
            for _ in range(20):
                if reconcile_mock.call_count:
                    break
                await asyncio.sleep(0.01)
            service._stop.set()
            await task

        self.assertGreaterEqual(reconcile_mock.call_count, 1)
        _, kwargs = reconcile_mock.call_args
        self.assertEqual(
            kwargs["source"],
            "bybit_websocket:periodic_rest_refresh",
        )
        status = service.get_status()
        self.assertEqual(
            status["last_reconciliation"]["reason"],
            "periodic_rest_refresh",
        )


if __name__ == "__main__":
    unittest.main()

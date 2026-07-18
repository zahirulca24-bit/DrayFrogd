from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from starlette.requests import Request

from app.entry_authority_runtime import ENTRY_AUTHORITY_DRY_RUN_PATH, handle_entry_authority_dry_run
from app.scalping_entry_authority import APPROVE


class EntryAuthorityRuntimeEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_dry_run_uses_orderbook_and_does_not_submit_order(self) -> None:
        fake_client = FakeExchangeClient()
        request = self._request(self._payload(), authenticated=True)

        with patch("app.entry_authority_runtime.get_execution_mode", return_value="demo"), patch(
            "app.entry_authority_runtime.get_exchange_client", return_value=fake_client
        ), patch("app.entry_authority_runtime.log_bot_event") as log_event:
            response = await handle_entry_authority_dry_run(request)

        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["decision"], APPROVE)
        self.assertEqual(body["mode"], "dry_run_no_order_submission")
        self.assertEqual(body["quote"]["source"], "orderbook")
        self.assertEqual(fake_client.order_submit_calls, 0)
        log_event.assert_called_once()

    async def test_unauthenticated_dry_run_is_blocked(self) -> None:
        request = self._request(self._payload(), authenticated=False)
        response = await handle_entry_authority_dry_run(request)
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(body["detail"], "Unauthorized")

    def _payload(self) -> dict:
        return {
            "symbol": "ZECUSDT",
            "strategy_name": "compression_expansion_v1",
            "trade_type": "scalping",
            "direction": "long",
            "entry": 50.0,
            "stop_loss": 49.7,
            "take_profit": 50.6,
            "risk_reward": 2.0,
            "detected_at": datetime.now(UTC).isoformat(),
            "status": "active",
            "allowed_entry_min": 50.0,
            "allowed_entry_max": 50.08,
        }

    def _request(self, payload: dict, *, authenticated: bool) -> Request:
        body = json.dumps(payload).encode("utf-8")

        async def receive() -> dict:
            return {"type": "http.request", "body": body, "more_body": False}

        scope = {
            "type": "http",
            "method": "POST",
            "path": ENTRY_AUTHORITY_DRY_RUN_PATH,
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
        }
        request = Request(scope, receive)
        request.state.session = {"sub": "tester", "tid": "token"} if authenticated else None
        return request


class FakeExchangeClient:
    def __init__(self) -> None:
        self.order_submit_calls = 0

    def safe_fetch_orderbook(self, symbol: str, limit: int = 1):
        return True, {"bids": [{"price": "50.02", "size": "100"}], "asks": [{"price": "50.03", "size": "100"}]}, None

    def safe_fetch_recent_candles(self, symbol: str, interval: str, limit: int = 35):
        candles = [{"high": 50.05, "low": 49.95} for _ in range(35)]
        return True, candles, None

    def place_order(self, *args, **kwargs):
        self.order_submit_calls += 1
        raise AssertionError("dry-run endpoint must not submit orders")


if __name__ == "__main__":
    unittest.main()

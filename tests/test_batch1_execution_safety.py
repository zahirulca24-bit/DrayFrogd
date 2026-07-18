from __future__ import annotations

import unittest
from unittest.mock import patch

from app.batch1_execution_safety import (
    enrich_readiness_with_ws,
    get_daily_loss_authority,
    normalize_execution_block,
)
from app.bybit_websocket import BybitWebSocketService


class FakeLedgerClient:
    mode = "demo"

    @staticmethod
    def safe_fetch_transaction_log(**kwargs):  # noqa: ANN003
        return (
            True,
            [
                {
                    "transactionTime": "1784358000000",
                    "type": "TRADE",
                    "symbol": "BTCUSDT",
                    "change": "-12.5",
                    "fee": "-2.5",
                    "cashBalance": "987.5",
                },
                {
                    "transactionTime": "1784358060000",
                    "type": "TRADE",
                    "symbol": "ETHUSDT",
                    "change": "4.0",
                    "fee": "-1.0",
                    "cashBalance": "991.5",
                },
            ],
            None,
        )


class FakeSocket:
    auth = True

    @staticmethod
    def is_connected() -> bool:
        return True


class Batch1ExecutionSafetyTests(unittest.TestCase):
    def test_expected_active_symbol_rejection_is_normalized_to_bounded_block(self) -> None:
        result = normalize_execution_block(
            {"ok": False, "error": "Symbol already has an active trade"}
        )
        self.assertEqual(result["error"], "SYMBOL_ALREADY_ACTIVE")
        self.assertTrue(result["execution_blocked"])
        self.assertEqual(result["detail"], "Symbol already has an active trade")

    def test_private_ws_degradation_is_explicit_rest_fallback_not_full_ready(self) -> None:
        readiness = {
            "ready_for_execution": True,
            "checks": {"admin_auth_configured": True},
        }
        enriched = enrich_readiness_with_ws(
            readiness,
            {
                "private": {
                    "connected": False,
                    "authenticated": False,
                    "state": "reconnecting",
                    "reconnect_count": 3,
                },
                "public": {"connected": True, "state": "connected"},
            },
        )
        self.assertEqual(enriched["execution_readiness_state"], "DEGRADED_REST_FALLBACK")
        self.assertEqual(
            enriched["execution_identity_policy"],
            "rest_execution_list_authoritative_fallback",
        )
        self.assertTrue(enriched["ready_for_execution"])
        self.assertEqual(enriched["websocket"]["private_reconnect_count"], 3)

    def test_private_ws_authenticated_reports_ready(self) -> None:
        enriched = enrich_readiness_with_ws(
            {"ready_for_execution": True, "checks": {"admin_auth_configured": True}},
            {
                "private": {"connected": True, "authenticated": True, "state": "connected"},
                "public": {"connected": True, "state": "connected"},
            },
        )
        self.assertEqual(enriched["execution_readiness_state"], "READY")
        self.assertEqual(
            enriched["execution_identity_policy"],
            "private_ws_plus_rest_reconciliation",
        )

    def test_rest_failure_reports_blocked_even_if_ws_status_exists(self) -> None:
        enriched = enrich_readiness_with_ws(
            {"ready_for_execution": False, "checks": {"admin_auth_configured": True}},
            {
                "private": {"connected": True, "authenticated": True},
                "public": {"connected": True},
            },
        )
        self.assertEqual(enriched["execution_readiness_state"], "BLOCKED")
        self.assertFalse(enriched["ready_for_execution"])

    def test_bybit_transaction_log_is_daily_loss_authority(self) -> None:
        authority = get_daily_loss_authority(client=FakeLedgerClient(), force=True)
        self.assertTrue(authority["ok"])
        self.assertEqual(authority["source"], "bybit_account_transaction_log")
        self.assertAlmostEqual(authority["trade_net"], -8.5)
        self.assertAlmostEqual(authority["account_net"], -8.5)
        self.assertAlmostEqual(authority["fees"], 3.5)
        self.assertEqual(authority["trade_count"], 2)

    def test_private_execution_callback_routes_records_to_persistence(self) -> None:
        service = BybitWebSocketService()
        service._private_ws = FakeSocket()
        record = {
            "symbol": "BTCUSDT",
            "orderId": "order-1",
            "orderLinkId": "link-1",
            "execId": "exec-1",
            "execQty": "1",
            "execPrice": "100",
        }
        with patch("app.batch1_execution_safety.persist_private_execution_records") as persist:
            service._private_callback({"topic": "execution", "data": [record]})
        persist.assert_called_once_with([record])


if __name__ == "__main__":
    unittest.main()

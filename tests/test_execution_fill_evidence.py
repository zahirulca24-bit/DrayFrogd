from __future__ import annotations

import unittest

from app.execution_fill_evidence import fetch_execution_fill_evidence, install


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def _private_get(self, path: str, params: dict[str, str]):
        self.calls += 1
        return {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "orderId": "order-123",
                    "orderLinkId": "df-test-link",
                    "execId": "exec-1",
                    "side": "Buy",
                    "positionIdx": 0,
                    "execPrice": "100.0",
                    "execQty": "0.10",
                    "execFee": "0.006",
                    "execTime": "1783828800000",
                },
                {
                    "symbol": "BTCUSDT",
                    "orderId": "order-123",
                    "orderLinkId": "df-test-link",
                    "execId": "exec-2",
                    "side": "Buy",
                    "positionIdx": 0,
                    "execPrice": "101.0",
                    "execQty": "0.20",
                    "execFee": "0.012",
                    "execTime": "1783828801000",
                },
            ]
        }


class ExecutionFillEvidenceTests(unittest.TestCase):
    def test_execution_records_create_fill_evidence(self) -> None:
        fill, error = fetch_execution_fill_evidence(
            FakeClient(),
            symbol="BTCUSDT",
            direction="long",
            order_link_id="df-test-link",
            order_id="order-123",
        )

        self.assertIsNone(error)
        self.assertIsNotNone(fill)
        assert fill is not None
        self.assertEqual(fill["source"], "bybit_execution_list")
        self.assertEqual(fill["order_id"], "order-123")
        self.assertEqual(fill["order_link_id"], "df-test-link")
        self.assertEqual(fill["exec_id"], "exec-1")
        self.assertEqual(fill["exec_ids"], ["exec-1", "exec-2"])
        self.assertAlmostEqual(fill["quantity"], 0.30)
        self.assertAlmostEqual(fill["fee"], 0.018)

    def test_install_is_idempotent(self) -> None:
        install()
        install()


if __name__ == "__main__":
    unittest.main()

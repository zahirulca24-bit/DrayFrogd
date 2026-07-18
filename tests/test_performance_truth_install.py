from __future__ import annotations

import json
import unittest

from app import execution, metrics
from app.performance_truth_install import (
    AuthoritativeTradeHistory,
    _merge_closed_truth,
    _trade_identity_key,
)


class PerformanceTruthInstallTests(unittest.TestCase):
    def test_empty_authoritative_history_is_truthy_to_block_legacy_fallback(self) -> None:
        history = AuthoritativeTradeHistory()
        self.assertEqual(list(history), [])
        self.assertTrue(history)
        self.assertEqual(json.dumps(history), "[]")

    def test_operational_and_metrics_history_use_same_filtered_authority(self) -> None:
        self.assertIs(execution.get_closed_trades, metrics.get_closed_trades)

    def test_durable_row_wins_over_duplicate_memory_row(self) -> None:
        durable = {
            "journal_id": "journal-1",
            "order_id": "order-1",
            "status": "closed",
            "realized_pnl": 5.0,
            "fees": 0.5,
            "exchange_metadata": {"close_sync": {"source": "bybit_position_closed_pnl"}},
        }
        stale_memory = {
            "journal_id": "journal-1",
            "order_id": "order-1",
            "status": "closed",
            "realized_pnl": None,
            "fees": None,
        }

        merged = _merge_closed_truth([durable], [stale_memory])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["realized_pnl"], 5.0)
        self.assertEqual(merged[0]["fees"], 0.5)

    def test_cross_field_identity_deduplicates_stale_memory_row(self) -> None:
        durable = {
            "journal_id": "journal-1",
            "execution_key": "exec-1",
            "order_id": "order-1",
            "status": "closed",
        }
        memory = {
            "order_id": "order-1",
            "status": "closed",
        }

        merged = _merge_closed_truth([durable], [memory])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["journal_id"], "journal-1")

    def test_non_duplicate_memory_row_is_retained(self) -> None:
        durable = {"journal_id": "journal-1", "status": "closed"}
        memory = {"journal_id": "journal-2", "status": "closed"}

        merged = _merge_closed_truth([durable], [memory])

        self.assertEqual([row["journal_id"] for row in merged], ["journal-1", "journal-2"])

    def test_identity_key_prefers_journal_then_execution_then_order(self) -> None:
        self.assertEqual(
            _trade_identity_key({"journal_id": "journal-1", "execution_key": "exec-1", "order_id": "order-1"}),
            "journal_id:journal-1",
        )
        self.assertEqual(
            _trade_identity_key({"execution_key": "exec-1", "order_id": "order-1"}),
            "execution_key:exec-1",
        )
        self.assertEqual(
            _trade_identity_key({"order_id": "order-1"}),
            "order_id:order-1",
        )

    def test_fallback_identity_is_stable_for_legacy_rows(self) -> None:
        first = {
            "symbol": "BTCUSDT",
            "direction": "long",
            "opened_at": "2026-07-18T01:00:00+00:00",
            "quantity": 1,
        }
        second = dict(first)
        self.assertEqual(_trade_identity_key(first), _trade_identity_key(second))


if __name__ == "__main__":
    unittest.main()

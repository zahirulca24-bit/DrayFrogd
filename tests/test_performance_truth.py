from __future__ import annotations

import unittest

from app.performance_truth import annotate_trade_truth, filter_performance_trades, performance_decision


class PerformanceTruthTests(unittest.TestCase):
    def authoritative_closed_trade(self) -> dict:
        return {
            "journal_id": "trade-1",
            "status": "closed",
            "result": "profit",
            "close_reason": "exchange_closed_pnl",
            "exit_price": 105.0,
            "realized_pnl": 4.25,
            "fees": 0.75,
            "exchange_metadata": {
                "close_sync": {
                    "source": "bybit_position_closed_pnl",
                    "identity_match": "exact",
                    "close_order_ids": ["close-order-1"],
                    "record_keys": ["id:close-order-1"],
                    "records": [{"orderId": "close-order-1", "execId": "close-exec-1"}],
                }
            },
        }

    def test_exchange_active_trade_counts_but_is_not_performance_eligible(self) -> None:
        annotated = annotate_trade_truth({"status": "active"})
        self.assertTrue(annotated["counts_as_trade"])
        self.assertFalse(annotated["performance_eligible"])
        self.assertEqual(annotated["trade_count_reason"], "exchange_active")

    def test_rejected_order_is_excluded_from_every_financial_count(self) -> None:
        annotated = annotate_trade_truth(
            {
                "status": "closed",
                "result": "execution_failed",
                "close_reason": "ORDER_NOT_ACCEPTED",
                "exit_price": None,
                "realized_pnl": None,
                "fees": None,
                "exchange_metadata": {},
            }
        )
        self.assertFalse(annotated["counts_as_trade"])
        self.assertFalse(annotated["performance_eligible"])
        self.assertEqual(annotated["performance_exclusion_reason"], "order_rejected_or_not_accepted")

    def test_sync_pending_trade_is_not_performance_eligible(self) -> None:
        annotated = annotate_trade_truth({"status": "close_pending_sync"})
        self.assertFalse(annotated["counts_as_trade"])
        self.assertFalse(annotated["performance_eligible"])
        self.assertEqual(annotated["financial_reconciliation_status"], "pending")

    def test_closed_trade_missing_fee_is_excluded(self) -> None:
        trade = self.authoritative_closed_trade()
        trade["fees"] = None
        decision = performance_decision(trade)
        self.assertFalse(decision["eligible"])
        self.assertEqual(decision["reason"], "missing_fees")

    def test_exact_authoritative_close_is_eligible(self) -> None:
        annotated = annotate_trade_truth(self.authoritative_closed_trade())
        self.assertTrue(annotated["counts_as_trade"])
        self.assertTrue(annotated["performance_eligible"])
        self.assertEqual(annotated["financial_reconciliation_status"], "reconciled")
        self.assertEqual(annotated["financial_truth_source"], "bybit_position_closed_pnl")

    def test_hash_only_record_key_does_not_satisfy_exact_identity(self) -> None:
        trade = self.authoritative_closed_trade()
        trade["exchange_metadata"]["close_sync"] = {
            "source": "bybit_account_transaction_log",
            "record_keys": ["hash:abc123"],
            "records": [{"record_key": "hash:abc123"}],
        }
        decision = performance_decision(trade)
        self.assertFalse(decision["eligible"])
        self.assertEqual(decision["reason"], "authoritative_close_identity_missing")

    def test_transaction_identity_is_accepted(self) -> None:
        trade = self.authoritative_closed_trade()
        trade["exchange_metadata"]["close_sync"] = {
            "source": "bybit_account_transaction_log",
            "record_keys": ["id:transaction-1"],
            "records": [{"transaction_id": "transaction-1"}],
        }
        self.assertTrue(performance_decision(trade)["eligible"])

    def test_filter_keeps_only_financially_reconciled_closed_rows(self) -> None:
        rejected = {
            "status": "closed",
            "result": "execution_failed",
            "close_reason": "ORDER_NOT_ACCEPTED",
        }
        pending = {"status": "close_pending_sync"}
        rows = filter_performance_trades([self.authoritative_closed_trade(), rejected, pending])
        self.assertEqual([row["journal_id"] for row in rows], ["trade-1"])


if __name__ == "__main__":
    unittest.main()

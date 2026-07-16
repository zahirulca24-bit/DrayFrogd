from __future__ import annotations

import unittest
from unittest.mock import patch

from app.execution_service import _fail_before_order
from app.metrics import get_metrics


class FakePositionClient:
    def safe_fetch_positions(self):
        return True, [{"symbol": "HYPEUSDT", "size": "40.36"}], None


class P05RuntimeTruthTests(unittest.TestCase):
    def test_pre_order_failure_is_not_classified_as_a_closed_trade(self) -> None:
        with (
            patch("app.execution_service._safe_update_trade_entry") as update_mock,
            patch("app.execution_service.release_active_trade") as release_mock,
        ):
            result = _fail_before_order(
                journal_id="exec-1",
                symbol="SOXLUSDT",
                error="ORDER_NOT_ACCEPTED",
                detail="exchange rejected order",
                metadata={"risk_approval": {"decision_id": "risk-1"}},
                sizing={"allowed": True},
            )

        self.assertFalse(result["ok"])
        updates = update_mock.call_args.args[1]
        self.assertEqual(updates["status"], "execution_failed")
        self.assertEqual(updates["result"], "execution_failed")
        self.assertIsNone(updates["closed_at"])
        self.assertIn("failed_at", updates["exchange_metadata"])
        release_mock.assert_called_once_with("SOXLUSDT")

    def test_performance_open_count_uses_exchange_position_truth(self) -> None:
        closed = {
            "journal_id": "closed-1",
            "status": "closed",
            "realized_pnl": 1.0,
            "result": "profit",
        }
        with (
            patch("app.metrics.get_snapshot", return_value={"version": 0, "trades": []}),
            patch("app.metrics.get_operator_active_trades", return_value=[]),
            patch("app.metrics.get_closed_trades", return_value=[closed]),
            patch("app.metrics.get_trade_history", return_value=[closed]),
            patch(
                "app.metrics._daily_financial_truth",
                return_value={
                    "today_realized_pnl": 0.0,
                    "today_account_net_pnl": 0.0,
                    "today_trade_net_pnl": 0.0,
                    "today_fees": 0.0,
                    "today_funding": 0.0,
                    "today_financial_date": "2026-07-17",
                    "today_financial_status": "authoritative",
                    "today_financial_source": "bybit_transaction_log",
                    "financial_truth_error": None,
                    "journal_today_realized_pnl": 0.0,
                    "journal_today_fees": 0.0,
                    "reconciliation_gap": 0.0,
                    "ledger_record_count": 0,
                },
            ),
        ):
            metrics = get_metrics(FakePositionClient())

        self.assertEqual(metrics["active_trades_count"], 1)
        self.assertEqual(metrics["closed_trades_count"], 1)
        self.assertEqual(metrics["total_trades"], 2)


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.metrics import get_metrics


class FakeLedgerClient:
    def __init__(self, *, ok=True):
        self.ok = ok

    def safe_fetch_transaction_log(self, *, start_time, end_time, limit):
        if not self.ok:
            return False, [], "ledger unavailable"
        return True, [
            {
                "transactionTime": str(int(datetime(2026, 7, 16, 12, 0, tzinfo=UTC).timestamp() * 1000)),
                "symbol": "ONDOUSDT",
                "type": "Trade",
                "side": "Sell",
                "fee": "0.5",
                "cashFlow": "12.0",
                "change": "11.5",
                "cashBalance": "944.0",
            },
            {
                "transactionTime": str(int(datetime(2026, 7, 16, 12, 5, tzinfo=UTC).timestamp() * 1000)),
                "symbol": "",
                "type": "Funding Rate Settlement",
                "funding": "0.25",
                "change": "0.25",
                "cashBalance": "944.25",
            },
        ], None


class FinancialTruthMetricsTests(unittest.TestCase):
    """Journal, Performance and Dashboard must share one explicit BDT-day truth source."""

    @patch("app.metrics.get_trade_history", return_value=[])
    @patch("app.metrics.get_closed_trade_history", return_value=[])
    @patch("app.metrics.get_closed_trades", return_value=[])
    @patch("app.metrics.get_operator_active_trades", return_value=[])
    @patch("app.metrics.get_snapshot", return_value={"version": 0, "trades": [], "mode": "demo"})
    def test_bybit_ledger_is_authoritative_daily_truth(self, *_mocks):
        result = get_metrics(
            FakeLedgerClient(),
            now=datetime(2026, 7, 16, 13, 0, tzinfo=UTC),
            bdt_date="2026-07-16",
        )

        self.assertEqual(result["today_financial_status"], "authoritative")
        self.assertEqual(result["today_financial_source"], "bybit_transaction_log")
        self.assertAlmostEqual(result["today_account_net_pnl"], 11.75)
        self.assertAlmostEqual(result["today_trade_net_pnl"], 11.5)
        self.assertAlmostEqual(result["today_fees"], 0.5)
        self.assertAlmostEqual(result["today_funding"], 0.25)
        self.assertEqual(result["ledger_record_count"], 2)

    @patch("app.metrics.get_trade_history", return_value=[])
    @patch("app.metrics.get_closed_trade_history", return_value=[])
    @patch("app.metrics.get_closed_trades", return_value=[])
    @patch("app.metrics.get_operator_active_trades", return_value=[])
    @patch("app.metrics.get_snapshot", return_value={"version": 0, "trades": [], "mode": "demo"})
    def test_unavailable_ledger_is_not_claimed_as_authoritative_zero(self, *_mocks):
        result = get_metrics(
            FakeLedgerClient(ok=False),
            now=datetime(2026, 7, 16, 13, 0, tzinfo=UTC),
            bdt_date="2026-07-16",
        )

        self.assertEqual(result["today_financial_status"], "unavailable")
        self.assertEqual(result["today_financial_source"], "unavailable")
        self.assertEqual(result["today_account_net_pnl"], 0.0)
        self.assertIn("ledger unavailable", result["financial_truth_error"])

    @patch("app.metrics.get_trade_history")
    @patch("app.metrics.get_closed_trade_history", return_value=[])
    @patch("app.metrics.get_closed_trades", return_value=[])
    @patch("app.metrics.get_operator_active_trades", return_value=[])
    @patch("app.metrics.get_snapshot", return_value={"version": 0, "trades": [], "mode": "demo"})
    def test_journal_fallback_is_explicit_when_ledger_fails(self, _snapshot, _active, _closed, _closed_history, trade_history):
        trade_history.return_value = [
            {
                "status": "closed",
                "closed_at": "2026-07-16T12:00:00+00:00",
                "realized_pnl": "5.25",
                "fees": "0.75",
            }
        ]
        result = get_metrics(
            FakeLedgerClient(ok=False),
            now=datetime(2026, 7, 16, 13, 0, tzinfo=UTC),
            bdt_date="2026-07-16",
        )

        self.assertEqual(result["today_financial_status"], "fallback")
        self.assertEqual(result["today_financial_source"], "journal_fallback")
        self.assertAlmostEqual(result["today_account_net_pnl"], 5.25)
        self.assertAlmostEqual(result["today_fees"], 0.75)


if __name__ == "__main__":
    unittest.main()

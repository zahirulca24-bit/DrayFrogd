import unittest
from unittest.mock import patch

from app.reconciliation_persistence import _mark_journal_stale, _persist_pending_close_sync


class ReconciliationPersistenceTests(unittest.TestCase):
    def test_missing_exact_close_remains_pending_not_closed(self) -> None:
        stale = _mark_journal_stale(
            {
                "journal_id": "jrnl-pending",
                "symbol": "BTCUSDT",
                "status": "active",
                "exchange_metadata": {},
            },
            error="exact close data unavailable",
        )

        self.assertEqual(stale["status"], "close_pending_sync")
        self.assertEqual(stale["exchange_metadata"]["close_sync"]["status"], "pending")

        with patch("app.reconciliation_persistence.update_trade_entry") as update_mock, patch(
            "app.reconciliation_persistence.append_trade_event"
        ):
            _persist_pending_close_sync("jrnl-pending", stale)

        updates = update_mock.call_args.args[1]
        self.assertEqual(updates["status"], "close_pending_sync")


if __name__ == "__main__":
    unittest.main()

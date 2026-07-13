import unittest

from app.strategy_audit import build_strategy_audit


OPENED_AT = "2026-07-14T12:00:00+00:00"


class StrategyAuditTests(unittest.TestCase):
    def test_strategy_audit_uses_bybit_ledger_pnl_and_win_loss(self) -> None:
        journal_trades = [
            {
                "journal_id": "jrnl-1",
                "symbol": "SOLUSDT",
                "strategy_name": "ema_pullback",
                "direction": "short",
                "entry": 75.23,
                "quantity": 59.6,
                "status": "closed",
                "opened_at": OPENED_AT,
                "closed_at": "2026-07-14T12:05:00+00:00",
            }
        ]
        ledger_records = [
            {
                "symbol": "SOLUSDT",
                "type": "Trade",
                "direction": "Open Sell",
                "qty": "59.6",
                "filledPrice": "75.23",
                "fee": "2.4660",
                "cashFlow": "0",
                "change": "-2.4660",
                "transactionTime": "1784030461000",
                "orderId": "open-1",
            },
            {
                "symbol": "SOLUSDT",
                "type": "Trade",
                "direction": "Close Buy",
                "qty": "59.6",
                "filledPrice": "74.75",
                "fee": "0.4455",
                "cashFlow": "14.3040",
                "change": "13.8585",
                "transactionTime": "1784030761000",
                "orderId": "close-1",
            },
        ]

        audit = build_strategy_audit(journal_trades=journal_trades, ledger_records=ledger_records, bdt_date="2026-07-14")

        self.assertTrue(audit["ok"])
        self.assertEqual(audit["summary"]["ledger_matched_trades"], 1)
        self.assertEqual(audit["summary"]["wins"], 1)
        self.assertAlmostEqual(audit["summary"]["net_pnl"], 11.3925)
        strategy = audit["strategies"][0]
        self.assertEqual(strategy["strategy"], "ema_pullback")
        self.assertEqual(strategy["wins"], 1)
        self.assertEqual(strategy["losses"], 0)
        self.assertAlmostEqual(strategy["net_pnl"], 11.3925)
        self.assertEqual(audit["trades"][0]["pnl_source"], "bybit_ledger")

    def test_strategy_audit_does_not_fabricate_zero_when_pnl_unknown(self) -> None:
        journal_trades = [
            {
                "journal_id": "jrnl-unknown",
                "symbol": "BTCUSDT",
                "strategy_name": "breakout",
                "direction": "long",
                "entry": 100.0,
                "quantity": 1.0,
                "status": "closed",
                "opened_at": OPENED_AT,
                "closed_at": "2026-07-14T12:05:00+00:00",
                "realized_pnl": None,
            }
        ]

        audit = build_strategy_audit(journal_trades=journal_trades, ledger_records=[], bdt_date="2026-07-14")

        self.assertEqual(audit["summary"]["known_pnl_trades"], 0)
        self.assertEqual(audit["summary"]["unmatched_trades"], 1)
        self.assertEqual(audit["strategies"][0]["known_pnl_trades"], 0)
        self.assertEqual(audit["strategies"][0]["net_pnl"], 0.0)
        self.assertFalse(audit["trades"][0]["pnl_known"])
        self.assertIsNone(audit["trades"][0]["realized_pnl"])


if __name__ == "__main__":
    unittest.main()

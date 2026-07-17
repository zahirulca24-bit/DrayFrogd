from __future__ import annotations

import unittest
from unittest.mock import patch

from app.execution import _active_order_ids, _active_trades, _closed_trades, close_trade


class ExecutionSLForensicsWireTests(unittest.TestCase):
    def setUp(self) -> None:
        _active_trades.clear()
        _closed_trades.clear()
        _active_order_ids.clear()

    def tearDown(self) -> None:
        _active_trades.clear()
        _closed_trades.clear()
        _active_order_ids.clear()

    def test_public_close_trade_persists_sl_forensics_for_stop_loss(self) -> None:
        trade = {
            "journal_id": "jrnl-sl-wire",
            "symbol": "BTCUSDT",
            "strategy_name": "ema_rejection",
            "trade_type": "scalping",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 99.0,
            "take_profit": 102.5,
            "quantity": 1.0,
            "remaining_quantity": 1.0,
            "order_id": "order-1",
            "status": "active",
            "opened_at": "2026-07-17T09:00:00+00:00",
            "exchange_metadata": {
                "existing": "kept",
                "management": {"trade_type": "scalping", "profile_name": "scalping_v2"},
            },
        }
        _active_trades.append(trade)
        _active_order_ids.append("order-1")

        with (
            patch("app.execution_core.update_trade_entry", return_value={}) as update_trade_entry,
            patch("app.execution_core.start_loss_cooldown") as start_loss_cooldown,
        ):
            closed = close_trade(
                "jrnl-sl-wire",
                {
                    "result": "sl",
                    "close_reason": "EXCHANGE_STOP_LOSS",
                    "exit_price": 99.01,
                    "fees": 0.05,
                    "closed_at": "2026-07-17T09:05:00+00:00",
                },
            )

        self.assertIsNotNone(closed)
        assert closed is not None
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["sl_hit_reason"], "stop_price_confirmed")
        self.assertEqual(closed["exchange_metadata"]["existing"], "kept")
        self.assertEqual(closed["exchange_metadata"]["sl_forensics"]["schema_version"], "sl_forensics_v1")
        self.assertEqual(closed["exchange_metadata"]["sl_forensics"]["sl_hit_reason"], "stop_price_confirmed")
        self.assertIn("exit_near_stop", closed["exchange_metadata"]["sl_forensics"]["forensic_flags"])

        update_payload = update_trade_entry.call_args.args[1]
        self.assertEqual(update_payload["sl_hit_reason"], "stop_price_confirmed")
        self.assertEqual(update_payload["exchange_metadata"]["sl_forensics"]["sl_hit_reason"], "stop_price_confirmed")
        start_loss_cooldown.assert_called_once()
        self.assertEqual(_active_trades, [])
        self.assertEqual(_active_order_ids, [])


if __name__ == "__main__":
    unittest.main()

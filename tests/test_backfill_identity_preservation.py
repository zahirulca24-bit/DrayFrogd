from __future__ import annotations

import unittest

from app.backfill_identity_preservation import merge_backfill_updates


class BackfillIdentityPreservationTests(unittest.TestCase):
    def test_existing_strategy_and_exchange_identity_are_preserved(self) -> None:
        existing = {
            "journal_id": "exec-btc-1",
            "strategy_name": "breakout_retest",
            "exchange_metadata": {
                "mode": "demo",
                "source": "authoritative_execution",
                "order_link_id": "df-entry-link",
                "fill_confirmation": {
                    "order_id": "entry-order-1",
                    "exec_id": "entry-exec-1",
                    "exec_ids": ["entry-exec-1"],
                },
                "management": {
                    "tp1_order_id": "tp1-order-1",
                    "tp2_order_id": "tp2-order-1",
                },
            },
        }
        updates = {
            "status": "closed",
            "strategy_name": "exchange_backfill",
            "exchange_metadata": {
                "source": "exchange_transaction_log_backfill",
                "recovered": True,
                "close_sync": {
                    "close_order_ids": ["tp1-order-1", "tp2-order-1"],
                    "realized_pnl": 12.5,
                    "fees": 1.25,
                },
            },
        }

        merged = merge_backfill_updates(existing, updates)
        metadata = merged["exchange_metadata"]

        self.assertEqual(merged["strategy_name"], "breakout_retest")
        self.assertEqual(metadata["order_link_id"], "df-entry-link")
        self.assertEqual(metadata["fill_confirmation"]["exec_id"], "entry-exec-1")
        self.assertEqual(metadata["management"]["tp1_order_id"], "tp1-order-1")
        self.assertEqual(metadata["close_sync"]["realized_pnl"], 12.5)
        self.assertEqual(metadata["original_source"], "authoritative_execution")
        self.assertEqual(metadata["backfill_source"], "exchange_transaction_log_backfill")
        self.assertTrue(metadata["backfill_identity_preservation"]["preserved"])

    def test_existing_close_sync_fields_are_enriched_not_deleted(self) -> None:
        existing = {
            "strategy_name": "ema_rejection",
            "exchange_metadata": {
                "close_sync": {
                    "identity_match": "exact",
                    "matched_close_order_ids": ["close-1"],
                    "record_keys": ["old-record"],
                }
            },
        }
        updates = {
            "strategy_name": "exchange_backfill",
            "exchange_metadata": {
                "close_sync": {
                    "record_keys": ["new-record"],
                    "realized_pnl": -4.0,
                }
            },
        }

        merged = merge_backfill_updates(existing, updates)
        close_sync = merged["exchange_metadata"]["close_sync"]

        self.assertEqual(close_sync["identity_match"], "exact")
        self.assertEqual(close_sync["matched_close_order_ids"], ["close-1"])
        self.assertEqual(close_sync["record_keys"], ["new-record"])
        self.assertEqual(close_sync["realized_pnl"], -4.0)

    def test_exchange_backfill_strategy_is_used_when_original_is_unknown(self) -> None:
        merged = merge_backfill_updates(
            {
                "strategy_name": "unknown",
                "exchange_metadata": {"order_link_id": "df-entry-link"},
            },
            {
                "strategy_name": "exchange_backfill",
                "exchange_metadata": {"recovered": True},
            },
        )

        self.assertEqual(merged["strategy_name"], "exchange_backfill")
        self.assertEqual(merged["exchange_metadata"]["order_link_id"], "df-entry-link")


if __name__ == "__main__":
    unittest.main()

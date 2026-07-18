from __future__ import annotations

import unittest

from app.backfill_identity_preservation import _preserving_update, merge_backfill_updates


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
        self.assertEqual(metadata["source"], "authoritative_execution")
        self.assertEqual(metadata["order_link_id"], "df-entry-link")
        self.assertEqual(metadata["fill_confirmation"]["exec_id"], "entry-exec-1")
        self.assertEqual(metadata["management"]["tp1_order_id"], "tp1-order-1")
        self.assertEqual(metadata["close_sync"]["realized_pnl"], 12.5)
        self.assertEqual(metadata["original_source"], "authoritative_execution")
        self.assertEqual(metadata["backfill_source"], "exchange_transaction_log_backfill")
        self.assertTrue(metadata["backfill_identity_preservation"]["preserved"])

    def test_existing_close_sync_evidence_is_unioned_not_deleted(self) -> None:
        existing = {
            "strategy_name": "ema_rejection",
            "exchange_metadata": {
                "close_sync": {
                    "identity_match": "exact",
                    "matched_close_order_ids": ["close-1"],
                    "record_keys": ["old-record"],
                    "records": [{"record_key": "old-record", "exec_id": "exec-1"}],
                    "record_count": 1,
                }
            },
        }
        updates = {
            "strategy_name": "exchange_backfill",
            "exchange_metadata": {
                "close_sync": {
                    "identity_match": "legacy_single_trade",
                    "matched_close_order_ids": ["close-2"],
                    "record_keys": ["new-record"],
                    "records": [{"record_key": "new-record", "exec_id": "exec-2"}],
                    "record_count": 1,
                    "realized_pnl": -4.0,
                }
            },
        }

        merged = merge_backfill_updates(existing, updates)
        close_sync = merged["exchange_metadata"]["close_sync"]

        self.assertEqual(close_sync["identity_match"], "exact")
        self.assertEqual(close_sync["matched_close_order_ids"], ["close-1", "close-2"])
        self.assertEqual(close_sync["record_keys"], ["old-record", "new-record"])
        self.assertEqual(
            [record["record_key"] for record in close_sync["records"]],
            ["old-record", "new-record"],
        )
        self.assertEqual(close_sync["record_count"], 2)
        self.assertEqual(close_sync["realized_pnl"], -4.0)

    def test_same_record_key_deduplicates_richer_backfill_record(self) -> None:
        merged = merge_backfill_updates(
            {
                "strategy_name": "ema_rejection",
                "exchange_metadata": {
                    "close_sync": {
                        "records": [{"record_key": "record-1", "exec_id": "exec-1"}],
                    }
                },
            },
            {
                "strategy_name": "exchange_backfill",
                "exchange_metadata": {
                    "close_sync": {
                        "records": [
                            {
                                "record_key": "record-1",
                                "exec_id": "exec-1",
                                "fee": 0.25,
                            }
                        ],
                    }
                },
            },
        )

        records = merged["exchange_metadata"]["close_sync"]["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["record_key"], "record-1")

    def test_nested_identity_lists_are_unioned(self) -> None:
        merged = merge_backfill_updates(
            {
                "strategy_name": "liquidity_sweep",
                "exchange_metadata": {
                    "fill_confirmation": {
                        "exec_id": "exec-1",
                        "exec_ids": ["exec-1"],
                    }
                },
            },
            {
                "strategy_name": "exchange_backfill",
                "exchange_metadata": {
                    "fill_confirmation": {
                        "exec_ids": ["exec-1", "exec-2"],
                    }
                },
            },
        )

        fill = merged["exchange_metadata"]["fill_confirmation"]
        self.assertEqual(fill["exec_id"], "exec-1")
        self.assertEqual(fill["exec_ids"], ["exec-1", "exec-2"])

    def test_malformed_nested_identity_does_not_delete_existing_evidence(self) -> None:
        merged = merge_backfill_updates(
            {
                "strategy_name": "breakout_retest",
                "exchange_metadata": {
                    "fill_confirmation": {
                        "exec_id": "exec-1",
                        "order_id": "order-1",
                    },
                    "management": {"tp1_order_id": "tp1-order-1"},
                },
            },
            {
                "strategy_name": "exchange_backfill",
                "exchange_metadata": {
                    "fill_confirmation": None,
                    "management": "invalid",
                },
            },
        )

        metadata = merged["exchange_metadata"]
        self.assertEqual(metadata["fill_confirmation"]["exec_id"], "exec-1")
        self.assertEqual(metadata["management"]["tp1_order_id"], "tp1-order-1")

    def test_preserving_update_fails_closed_when_existing_row_cannot_be_read(self) -> None:
        class MissingBackfill:
            @staticmethod
            def get_trade_history(limit: int):
                return []

        calls: list[tuple[str, dict]] = []

        def original(journal_id: str, updates: dict):
            calls.append((journal_id, updates))
            return {"journal_id": journal_id}

        result = _preserving_update(
            MissingBackfill(),
            original,
            "missing-journal",
            {"status": "closed", "exchange_metadata": {"recovered": True}},
        )

        self.assertIsNone(result)
        self.assertEqual(calls, [])

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

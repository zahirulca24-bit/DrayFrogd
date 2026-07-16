from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.exchange_journal_backfill import backfill_exchange_journal_lifecycle


# Fixed timestamps and record identities make the restart/idempotency contract deterministic.
OPEN_MS = int(datetime(2026, 7, 16, 12, 0, tzinfo=UTC).timestamp() * 1000)


def records() -> list[dict]:
    return [
        {
            "id": "open-1",
            "symbol": "ONDOUSDT",
            "type": "Trade",
            "direction": "Open Buy",
            "qty": "10",
            "filledPrice": "1.00",
            "fee": "0.10",
            "cashFlow": "0",
            "change": "-0.10",
            "transactionTime": str(OPEN_MS),
            "orderId": "entry-order",
        },
        {
            "id": "close-1",
            "symbol": "ONDOUSDT",
            "type": "Trade",
            "direction": "Close Sell",
            "qty": "4",
            "filledPrice": "1.20",
            "fee": "0.04",
            "cashFlow": "0.80",
            "change": "0.76",
            "transactionTime": str(OPEN_MS + 60_000),
            "orderId": "tp1-order",
        },
        {
            "id": "close-2",
            "symbol": "ONDOUSDT",
            "type": "Trade",
            "direction": "Close Sell",
            "qty": "6",
            "filledPrice": "1.10",
            "fee": "0.06",
            "cashFlow": "0.60",
            "change": "0.54",
            "transactionTime": str(OPEN_MS + 120_000),
            "orderId": "final-order",
        },
    ]


def plain_side_records() -> list[dict]:
    payload = [dict(record) for record in records()]
    payload[0]["direction"] = "Buy"
    payload[1]["direction"] = "Sell"
    payload[2]["direction"] = "Sell"
    return payload


class FakeClient:
    mode = "demo"

    def __init__(self, payload: list[dict] | None = None) -> None:
        self.payload = list(payload or records())

    def safe_fetch_transaction_log(self, **_kwargs):
        return True, list(self.payload), None


class ExchangeJournalBackfillTests(unittest.TestCase):
    def test_complete_partial_close_lifecycle_creates_one_closed_row(self) -> None:
        with (
            patch("app.exchange_journal_backfill.get_trade_history", return_value=[]),
            patch("app.exchange_journal_backfill.get_trade_by_execution_key", return_value=None),
            patch("app.exchange_journal_backfill.create_trade_entry", side_effect=lambda value: value) as create_mock,
        ):
            result = backfill_exchange_journal_lifecycle(
                FakeClient(),
                bdt_date="2026-07-16",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["created"]), 1)
        create_mock.assert_called_once()
        payload = create_mock.call_args.args[0]
        self.assertEqual(payload["status"], "closed")
        self.assertEqual(payload["symbol"], "ONDOUSDT")
        self.assertEqual(payload["direction"], "long")
        self.assertAlmostEqual(payload["quantity"], 10.0)
        self.assertAlmostEqual(payload["entry"], 1.0)
        self.assertAlmostEqual(payload["exit_price"], 1.14)
        self.assertAlmostEqual(payload["realized_pnl"], 1.20)
        self.assertAlmostEqual(payload["fees"], 0.20)
        self.assertEqual(payload["exchange_metadata"]["close_sync"]["record_count"], 3)

    def test_plain_buy_sell_rows_are_classified_from_lifecycle_sequence(self) -> None:
        with (
            patch("app.exchange_journal_backfill.get_trade_history", return_value=[]),
            patch("app.exchange_journal_backfill.get_trade_by_execution_key", return_value=None),
            patch("app.exchange_journal_backfill.create_trade_entry", side_effect=lambda value: value) as create_mock,
        ):
            result = backfill_exchange_journal_lifecycle(
                FakeClient(plain_side_records()),
                bdt_date="2026-07-16",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["pending"], [])
        create_mock.assert_called_once()
        payload = create_mock.call_args.args[0]
        self.assertEqual(payload["direction"], "long")
        self.assertEqual(payload["status"], "closed")
        self.assertAlmostEqual(payload["realized_pnl"], 1.20)
        self.assertAlmostEqual(payload["fees"], 0.20)

    def test_plain_side_close_without_open_is_not_fabricated(self) -> None:
        orphan = [dict(records()[1])]
        orphan[0]["direction"] = "Sell"
        with (
            patch("app.exchange_journal_backfill.get_trade_history", return_value=[]),
            patch("app.exchange_journal_backfill.create_trade_entry") as create_mock,
        ):
            result = backfill_exchange_journal_lifecycle(
                FakeClient(orphan),
                bdt_date="2026-07-16",
            )

        self.assertTrue(result["ok"])
        self.assertIn("no same-day open lifecycle", result["pending"][0]["error"])
        create_mock.assert_not_called()

    def test_existing_recovered_open_row_is_finalized_not_duplicated(self) -> None:
        existing = {
            "journal_id": "exchange-recovered",
            "execution_key": "recovered-key",
            "symbol": "ONDOUSDT",
            "direction": "long",
            "quantity": 10.0,
            "status": "active",
            "order_id": None,
            "exchange_metadata": {},
        }
        persisted = {**existing, "status": "closed"}
        with (
            patch("app.exchange_journal_backfill.get_trade_history", return_value=[existing]),
            patch("app.exchange_journal_backfill.update_trade_entry", return_value=persisted) as update_mock,
            patch("app.exchange_journal_backfill.append_trade_event") as event_mock,
            patch("app.exchange_journal_backfill.create_trade_entry") as create_mock,
        ):
            result = backfill_exchange_journal_lifecycle(
                FakeClient(),
                bdt_date="2026-07-16",
            )

        self.assertEqual(result["updated"], ["exchange-recovered"])
        update_mock.assert_called_once()
        updates = update_mock.call_args.args[1]
        self.assertEqual(updates["status"], "closed")
        self.assertAlmostEqual(updates["realized_pnl"], 1.20)
        event_mock.assert_called_once()
        create_mock.assert_not_called()

    def test_repeated_run_skips_already_closed_record_keys_without_new_event(self) -> None:
        existing = {
            "journal_id": "existing",
            "execution_key": "ledger-existing",
            "symbol": "ONDOUSDT",
            "direction": "long",
            "quantity": 10.0,
            "status": "closed",
            "exchange_metadata": {
                "close_sync": {"record_keys": ["id:open-1", "id:close-1", "id:close-2"]}
            },
        }
        with (
            patch("app.exchange_journal_backfill.get_trade_history", return_value=[existing]),
            patch("app.exchange_journal_backfill.update_trade_entry") as update_mock,
            patch("app.exchange_journal_backfill.append_trade_event") as event_mock,
            patch("app.exchange_journal_backfill.create_trade_entry") as create_mock,
        ):
            result = backfill_exchange_journal_lifecycle(
                FakeClient(),
                bdt_date="2026-07-16",
            )

        self.assertEqual(result["skipped"], ["existing"])
        update_mock.assert_not_called()
        event_mock.assert_not_called()
        create_mock.assert_not_called()

    def test_orphan_close_is_reported_without_fabricated_journal(self) -> None:
        orphan = records()[1:]
        with (
            patch("app.exchange_journal_backfill.get_trade_history", return_value=[]),
            patch("app.exchange_journal_backfill.create_trade_entry") as create_mock,
        ):
            result = backfill_exchange_journal_lifecycle(
                FakeClient(orphan),
                bdt_date="2026-07-16",
            )

        self.assertTrue(result["ok"])
        self.assertGreaterEqual(len(result["pending"]), 1)
        create_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

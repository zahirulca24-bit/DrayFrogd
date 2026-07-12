from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.risk_sync import sync_partial_realized_pnl


OPENED_AT = "2026-07-12T10:00:00+00:00"
CLOSED_MS = int(datetime(2026, 7, 12, 10, 5, tzinfo=UTC).timestamp() * 1000)
NOW = datetime(2026, 7, 12, 10, 10, tzinfo=UTC)


class FakeClosedPnlClient:
    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self.calls: list[dict] = []

    def safe_fetch_closed_pnl(self, *, symbol: str, start_time: int, end_time: int):
        self.calls.append({"symbol": symbol, "start_time": start_time, "end_time": end_time})
        return True, [dict(record) for record in self.records], None


def partial_record(**overrides) -> dict:
    record = {
        "symbol": "BTCUSDT",
        "side": "Sell",
        "orderId": "tp1-order",
        "closedSize": "5",
        "avgExitPrice": "103",
        "closedPnl": "14.10",
        "openFee": "0.40",
        "closeFee": "0.50",
        "updatedTime": str(CLOSED_MS),
    }
    record.update(overrides)
    return record


def active_trade(**overrides) -> dict:
    management = {
        "profile_name": "scalping_v2",
        "trade_type": "scalping",
        "initial_quantity": 10.0,
        "remaining_quantity": 5.0,
        "tp1_done": True,
        "tp2_done": False,
        "native_tp_enabled": True,
    }
    trade = {
        "journal_id": "jrnl-partial",
        "symbol": "BTCUSDT",
        "direction": "long",
        "entry": 100.0,
        "quantity": 5.0,
        "remaining_quantity": 5.0,
        "status": "active",
        "opened_at": OPENED_AT,
        "realized_pnl": None,
        "fees": None,
        "exit_price": None,
        "management": management,
        "exchange_metadata": {"management": management},
    }
    trade.update(overrides)
    return trade


class PartialCloseJournalSyncTests(unittest.TestCase):
    def test_persists_exact_partial_pnl_fees_exit_and_fill_lifecycle(self) -> None:
        trade = active_trade()
        client = FakeClosedPnlClient([partial_record()])
        active_updates: list[tuple[str, dict]] = []
        journal_updates: list[tuple[str, dict]] = []
        events: list[tuple[str, str, str, dict]] = []

        with (
            patch("app.risk_sync.get_active_trades", return_value=[trade]),
            patch("app.risk_sync.update_active_trade", side_effect=lambda journal_id, updates: active_updates.append((journal_id, updates))),
            patch("app.risk_sync.update_trade_entry", side_effect=lambda journal_id, updates: journal_updates.append((journal_id, updates)) or {"journal_id": journal_id}),
            patch("app.risk_sync.append_trade_event", side_effect=lambda *args: events.append(args)),
        ):
            result = sync_partial_realized_pnl(client, now=NOW)

        self.assertTrue(result["ok"])
        self.assertEqual(result["synced_count"], 1)
        self.assertEqual(len(journal_updates), 1)
        persisted = journal_updates[0][1]
        self.assertEqual(persisted["quantity"], 5.0)
        self.assertEqual(persisted["exit_price"], 103.0)
        self.assertEqual(persisted["realized_pnl"], 14.10)
        self.assertEqual(persisted["fees"], 0.90)
        self.assertEqual(persisted["exchange_metadata"]["partial_close_sync"]["record_keys"], ["order:tp1-order"])
        self.assertEqual(active_updates[0][1]["remaining_quantity"], 5.0)
        self.assertIn("PARTIAL_CLOSE_FILL_SYNCED", [event[1] for event in events])
        self.assertIn("PARTIAL_REALIZED_PNL_SYNCED", [event[1] for event in events])

    def test_repairs_stale_journal_columns_without_duplicate_fill_event(self) -> None:
        record = partial_record()
        existing_progress = {
            "source": "bybit_position_closed_pnl_partial",
            "closed_size": 5.0,
            "initial_quantity": 10.0,
            "remaining_quantity": 5.0,
            "avg_exit_price": 103.0,
            "realized_pnl": 14.10,
            "fees": 0.90,
            "record_keys": ["order:tp1-order"],
            "records": [],
        }
        trade = active_trade(
            exchange_metadata={
                "management": active_trade()["management"],
                "partial_close_sync": existing_progress,
                "risk_realized_progress": existing_progress,
            }
        )
        client = FakeClosedPnlClient([record])
        events: list[tuple[str, str, str, dict]] = []
        journal_updates: list[dict] = []

        with (
            patch("app.risk_sync.get_active_trades", return_value=[trade]),
            patch("app.risk_sync.update_active_trade"),
            patch("app.risk_sync.update_trade_entry", side_effect=lambda journal_id, updates: journal_updates.append(updates) or {"journal_id": journal_id}),
            patch("app.risk_sync.append_trade_event", side_effect=lambda *args: events.append(args)),
        ):
            result = sync_partial_realized_pnl(client, now=NOW)

        self.assertTrue(result["ok"])
        self.assertEqual(journal_updates[0]["realized_pnl"], 14.10)
        event_types = [event[1] for event in events]
        self.assertNotIn("PARTIAL_CLOSE_FILL_SYNCED", event_types)
        self.assertIn("PARTIAL_REALIZED_PNL_FIELDS_REPAIRED", event_types)

    def test_exchange_quantity_reduction_triggers_sync_before_local_tp_flags(self) -> None:
        trade = active_trade()
        trade["management"]["tp1_done"] = False
        trade["management"]["remaining_quantity"] = 10.0
        trade["quantity"] = 5.0
        trade["remaining_quantity"] = 5.0
        client = FakeClosedPnlClient([partial_record()])

        with (
            patch("app.risk_sync.get_active_trades", return_value=[trade]),
            patch("app.risk_sync.update_active_trade"),
            patch("app.risk_sync.update_trade_entry", return_value={"journal_id": trade["journal_id"]}) as journal_update,
            patch("app.risk_sync.append_trade_event"),
        ):
            result = sync_partial_realized_pnl(client, now=NOW)

        self.assertTrue(result["ok"])
        self.assertEqual(result["synced_count"], 1)
        journal_update.assert_called_once()

    def test_missing_exact_fee_fields_blocks_false_exact_sync(self) -> None:
        trade = active_trade()
        client = FakeClosedPnlClient([partial_record(closeFee=None)])

        with (
            patch("app.risk_sync.get_active_trades", return_value=[trade]),
            patch("app.risk_sync.update_active_trade") as active_update,
            patch("app.risk_sync.update_trade_entry") as journal_update,
            patch("app.risk_sync.append_trade_event"),
        ):
            result = sync_partial_realized_pnl(client, now=NOW)

        self.assertFalse(result["ok"])
        self.assertEqual(result["synced_count"], 0)
        self.assertIn("openFee/closeFee", result["errors"][0]["error"])
        active_update.assert_not_called()
        journal_update.assert_not_called()

    def test_identical_exact_state_is_idempotent(self) -> None:
        record = partial_record()
        existing_progress = {
            "source": "bybit_position_closed_pnl_partial",
            "closed_size": 5.0,
            "initial_quantity": 10.0,
            "remaining_quantity": 5.0,
            "avg_exit_price": 103.0,
            "realized_pnl": 14.10,
            "fees": 0.90,
            "record_keys": ["order:tp1-order"],
            "records": [],
        }
        trade = active_trade(
            realized_pnl=14.10,
            fees=0.90,
            exit_price=103.0,
            exchange_metadata={
                "management": active_trade()["management"],
                "partial_close_sync": existing_progress,
                "risk_realized_progress": existing_progress,
            },
        )
        client = FakeClosedPnlClient([record])

        with (
            patch("app.risk_sync.get_active_trades", return_value=[trade]),
            patch("app.risk_sync.update_active_trade") as active_update,
            patch("app.risk_sync.update_trade_entry") as journal_update,
            patch("app.risk_sync.append_trade_event") as append_event,
        ):
            result = sync_partial_realized_pnl(client, now=NOW)

        self.assertTrue(result["ok"])
        self.assertEqual(result["synced_count"], 0)
        active_update.assert_not_called()
        journal_update.assert_not_called()
        append_event.assert_not_called()

    def test_tp1_and_tp2_records_accumulate_without_double_counting(self) -> None:
        trade = active_trade(quantity=2.5, remaining_quantity=2.5)
        trade["management"]["remaining_quantity"] = 2.5
        trade["management"]["tp2_done"] = True
        tp2_time = CLOSED_MS + 60_000
        client = FakeClosedPnlClient(
            [
                partial_record(),
                partial_record(
                    orderId="tp2-order",
                    closedSize="2.5",
                    avgExitPrice="104",
                    closedPnl="9.25",
                    openFee="0.20",
                    closeFee="0.25",
                    updatedTime=str(tp2_time),
                ),
                partial_record(),
            ]
        )
        journal_updates: list[dict] = []
        events: list[tuple[str, str, str, dict]] = []

        with (
            patch("app.risk_sync.get_active_trades", return_value=[trade]),
            patch("app.risk_sync.update_active_trade"),
            patch("app.risk_sync.update_trade_entry", side_effect=lambda journal_id, updates: journal_updates.append(updates) or {"journal_id": journal_id}),
            patch("app.risk_sync.append_trade_event", side_effect=lambda *args: events.append(args)),
        ):
            result = sync_partial_realized_pnl(client, now=NOW)

        self.assertTrue(result["ok"])
        persisted = journal_updates[0]
        self.assertEqual(persisted["quantity"], 2.5)
        self.assertAlmostEqual(persisted["exit_price"], (103.0 * 5.0 + 104.0 * 2.5) / 7.5)
        self.assertAlmostEqual(persisted["realized_pnl"], 23.35)
        self.assertAlmostEqual(persisted["fees"], 1.35)
        progress = persisted["exchange_metadata"]["partial_close_sync"]
        self.assertEqual(progress["record_count"], 2)
        self.assertEqual(progress["record_keys"], ["order:tp1-order", "order:tp2-order"])
        self.assertEqual([event[1] for event in events].count("PARTIAL_CLOSE_FILL_SYNCED"), 2)


if __name__ == "__main__":
    unittest.main()

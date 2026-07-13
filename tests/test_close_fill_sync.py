import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.close_fill_sync import (
    _safe_fetch_closed_pnl,
    aggregate_closed_pnl_records,
    aggregate_transaction_log_records,
)
from app.reconciliation import reconcile_state


OPENED_AT = "2025-01-01T00:00:00+00:00"
OPENED_MS = int(datetime.fromisoformat(OPENED_AT).timestamp() * 1000)


def trade_payload() -> dict:
    return {
        "journal_id": "jrnl-1",
        "symbol": "BTCUSDT",
        "direction": "long",
        "entry": 100.0,
        "stop_loss": 98.0,
        "take_profit": 103.0,
        "quantity": 1.0,
        "remaining_quantity": 1.0,
        "opened_at": OPENED_AT,
        "status": "active",
        "management": {"initial_quantity": 1.0},
        "exchange_metadata": {"management": {"initial_quantity": 1.0}},
    }


def exact_records() -> list[dict]:
    return [
        {
            "symbol": "BTCUSDT",
            "side": "Sell",
            "orderId": "close-1",
            "closedSize": "0.4",
            "avgExitPrice": "110",
            "closedPnl": "4",
            "openFee": "0.04",
            "closeFee": "0.02",
            "fillCount": "2",
            "createdTime": str(OPENED_MS + 60_000),
            "updatedTime": str(OPENED_MS + 60_000),
        },
        {
            "symbol": "BTCUSDT",
            "side": "Sell",
            "orderId": "close-2",
            "closedSize": "0.6",
            "avgExitPrice": "112",
            "closedPnl": "7.2",
            "openFee": "0.06",
            "closeFee": "0.03",
            "fillCount": "3",
            "createdTime": str(OPENED_MS + 120_000),
            "updatedTime": str(OPENED_MS + 120_000),
        },
    ]


class ClosedPnlAggregationTests(unittest.TestCase):
    def test_partial_close_records_are_aggregated_exactly(self) -> None:
        result, error = aggregate_closed_pnl_records(trade_payload(), exact_records(), opened_ms=OPENED_MS)

        self.assertIsNone(error)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(result["exit_price"], 111.2)
        self.assertAlmostEqual(result["realized_pnl"], 11.2)
        self.assertAlmostEqual(result["fees"], 0.15)
        self.assertEqual(result["result"], "profit")
        self.assertEqual(result["close_reason"], "exchange_closed_pnl")
        close_sync = result["exchange_metadata"]["close_sync"]
        self.assertEqual(close_sync["record_count"], 2)
        self.assertEqual(close_sync["fill_count"], 5)
        self.assertEqual(close_sync["close_order_ids"], ["close-1", "close-2"])

    def test_missing_exact_fee_fields_does_not_fabricate_result(self) -> None:
        records = exact_records()
        records[1].pop("closeFee")

        result, error = aggregate_closed_pnl_records(trade_payload(), records, opened_ms=OPENED_MS)

        self.assertIsNone(result)
        self.assertEqual(error, "Bybit close record is missing exact openFee/closeFee fields")

    def test_partial_quantity_remains_pending(self) -> None:
        result, error = aggregate_closed_pnl_records(trade_payload(), exact_records()[:1], opened_ms=OPENED_MS)

        self.assertIsNone(result)
        self.assertIn("partial close data only", error or "")

    def test_private_api_fallback_paginates_closed_pnl(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def _private_get(self, path: str, params: dict):
                self.calls.append(dict(params))
                if not params.get("cursor"):
                    return {"list": [{"orderId": "1"}], "nextPageCursor": "next"}
                return {"list": [{"orderId": "2"}], "nextPageCursor": ""}

        client = Client()
        ok, records, error = _safe_fetch_closed_pnl(
            client,
            symbol="BTCUSDT",
            start_ms=OPENED_MS,
            end_ms=OPENED_MS + 60_000,
        )

        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertEqual([item["orderId"] for item in records], ["1", "2"])
        self.assertEqual(client.calls[0]["limit"], "100")
        self.assertEqual(client.calls[1]["cursor"], "next")

    def test_transaction_log_records_repair_exact_net_close(self) -> None:
        short_trade = {**trade_payload(), "direction": "short", "entry": 75.23, "quantity": 59.6}
        records = [
            {
                "symbol": "BTCUSDT",
                "type": "Trade",
                "direction": "Open Sell",
                "qty": "59.6",
                "filledPrice": "75.23",
                "fee": "2.4660",
                "cashFlow": "0",
                "change": "-2.4660",
                "transactionTime": str(OPENED_MS + 1_000),
            },
            {
                "symbol": "BTCUSDT",
                "type": "Trade",
                "direction": "Close Buy",
                "qty": "29.8",
                "filledPrice": "74.75",
                "fee": "0.4455",
                "cashFlow": "14.3040",
                "change": "13.8585",
                "transactionTime": str(OPENED_MS + 60_000),
            },
            {
                "symbol": "BTCUSDT",
                "type": "Trade",
                "direction": "Close Buy",
                "qty": "29.8",
                "filledPrice": "74.59",
                "fee": "0.2223",
                "cashFlow": "9.5360",
                "change": "9.3137",
                "transactionTime": str(OPENED_MS + 120_000),
            },
        ]

        result, error = aggregate_transaction_log_records(short_trade, records, opened_ms=OPENED_MS)

        self.assertIsNone(error)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(result["exit_price"], 74.67)
        self.assertAlmostEqual(result["realized_pnl"], 20.7062)
        self.assertAlmostEqual(result["fees"], 3.1338)
        self.assertEqual(result["result"], "profit")
        self.assertEqual(result["close_reason"], "exchange_transaction_log")
        self.assertEqual(result["exchange_metadata"]["close_sync"]["source"], "bybit_account_transaction_log")


class FakeReconciliationClient:
    def __init__(self, closed_records: list[dict]) -> None:
        self.closed_records = closed_records
        self.position_calls = 0

    def safe_fetch_open_orders(self):
        return True, [], None

    def safe_fetch_positions(self):
        self.position_calls += 1
        return True, [], None

    def safe_fetch_market_tickers(self):
        return True, [{"symbol": "BTCUSDT", "lastPrice": "999"}], None

    def safe_fetch_closed_pnl(self, symbol: str, start_time: int, end_time: int):
        return True, list(self.closed_records), None


class ReconciliationCloseSyncTests(unittest.TestCase):
    def test_reconciliation_uses_exact_close_not_ticker_estimate(self) -> None:
        client = FakeReconciliationClient(exact_records())
        closed = {**trade_payload(), "status": "closed"}

        with patch("app.reconciliation.get_active_trades", return_value=[trade_payload()]), patch(
            "app.reconciliation.close_trade", return_value=closed
        ) as close_mock, patch("app.reconciliation.replace_active_trades") as replace_mock, patch(
            "app.reconciliation.release_active_trade"
        ) as release_mock, patch("app.reconciliation.update_trade_entry"), patch(
            "app.reconciliation.append_trade_event"
        ):
            response = reconcile_state(client)

        self.assertTrue(response["ok"])
        close_fields = close_mock.call_args.args[1]
        self.assertAlmostEqual(close_fields["exit_price"], 111.2)
        self.assertNotEqual(close_fields["exit_price"], 999.0)
        self.assertAlmostEqual(close_fields["realized_pnl"], 11.2)
        self.assertAlmostEqual(close_fields["fees"], 0.15)
        replace_mock.assert_called_once_with([])
        release_mock.assert_called_once_with("BTCUSDT")

    def test_missing_exact_close_data_keeps_symbol_risk_blocked(self) -> None:
        client = FakeReconciliationClient([])

        with patch("app.reconciliation.get_active_trades", return_value=[trade_payload()]), patch(
            "app.reconciliation.close_trade"
        ) as close_mock, patch("app.reconciliation.replace_active_trades") as replace_mock, patch(
            "app.reconciliation.release_active_trade"
        ) as release_mock, patch("app.reconciliation.update_trade_entry") as update_mock, patch(
            "app.reconciliation.append_trade_event"
        ):
            response = reconcile_state(client)

        self.assertTrue(response["ok"])
        self.assertEqual(response["trades"][0]["status"], "close_pending_sync")
        self.assertIn("not available yet", response["trades"][0]["close_sync_error"])
        close_mock.assert_not_called()
        release_mock.assert_not_called()
        replace_mock.assert_called_once()
        update_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()

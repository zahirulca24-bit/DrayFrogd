import unittest
from unittest.mock import patch

from app.active_trade_control import enrich_active_trades, request_market_close
from app.exchange import ExchangeError


TRADE = {
    "journal_id": "jrnl-live-1",
    "symbol": "BTCUSDT",
    "direction": "long",
    "entry": 100.0,
    "stop_loss": 95.0,
    "take_profit": 110.0,
    "quantity": 2.0,
    "remaining_quantity": 2.0,
    "status": "active",
    "opened_at": "2026-07-12T00:00:00+00:00",
    "execution_mode": "demo",
    "exchange_metadata": {},
}

POSITION = {
    "symbol": "BTCUSDT",
    "side": "Buy",
    "size": "2",
    "avgPrice": "100",
    "markPrice": "110",
    "stopLoss": "95",
    "takeProfit": "110",
    "leverage": "5",
    "positionValue": "220",
    "positionIM": "44",
    "unrealisedPnl": "20",
    "liqPrice": "82",
}


class FakeCloseClient:
    def __init__(self, positions=None) -> None:
        self.positions = list(POSITION for _ in [0]) if positions is None else positions
        self.private_calls = []
        self.private_error = None
        self.lookup_result = (True, None, None)

    def safe_fetch_positions(self):
        return True, self.positions, None

    def _private_post(self, path, body):
        self.private_calls.append((path, body))
        if self.private_error:
            raise ExchangeError(self.private_error)
        return {"orderId": "close-order-1", "orderLinkId": body["orderLinkId"]}

    def safe_fetch_order_by_link_id(self, symbol, order_link_id):
        return self.lookup_result


class ActiveTradeControlTests(unittest.TestCase):
    def test_enriches_trade_with_authoritative_position_metrics(self) -> None:
        enriched = enrich_active_trades([TRADE], [POSITION], "demo", journal_factory=lambda trade: trade)

        self.assertEqual(len(enriched), 1)
        trade = enriched[0]
        self.assertEqual(trade["mark_price"], 110.0)
        self.assertEqual(trade["leverage"], 5.0)
        self.assertEqual(trade["position_value"], 220.0)
        self.assertEqual(trade["position_margin"], 44.0)
        self.assertEqual(trade["unrealized_pnl"], 20.0)
        self.assertAlmostEqual(trade["pnl_percent"], 45.45454545)
        self.assertEqual(trade["liquidation_price"], 82.0)
        self.assertTrue(trade["position_synced"])
        self.assertTrue(trade["live_metrics_available"])
        self.assertTrue(trade["close_allowed"])

    def test_close_reservation_failure_sends_no_order(self) -> None:
        client = FakeCloseClient()
        with patch("app.active_trade_control.get_active_trades", return_value=[TRADE]), patch(
            "app.active_trade_control.update_trade_entry", side_effect=RuntimeError("database offline")
        ):
            result = request_market_close(client, TRADE["journal_id"])

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "CLOSE_RESERVATION_FAILED")
        self.assertEqual(client.private_calls, [])

    def test_manual_close_is_reduce_only_and_deterministic(self) -> None:
        client = FakeCloseClient()
        persisted_updates = []

        def persist(journal_id, updates):
            persisted_updates.append((journal_id, updates))
            return {"journal_id": journal_id, **updates}

        with patch("app.active_trade_control.get_active_trades", return_value=[TRADE]), patch(
            "app.active_trade_control.update_trade_entry", side_effect=persist
        ), patch("app.active_trade_control.update_active_trade"), patch(
            "app.active_trade_control.append_trade_event"
        ):
            first = request_market_close(client, TRADE["journal_id"])

        self.assertTrue(first["ok"])
        self.assertEqual(first["status"], "close_requested")
        self.assertEqual(len(client.private_calls), 1)
        path, body = client.private_calls[0]
        self.assertEqual(path, "/v5/order/create")
        self.assertTrue(body["reduceOnly"])
        self.assertEqual(body["side"], "Sell")
        self.assertEqual(body["qty"], "2")
        self.assertTrue(body["orderLinkId"].startswith("df-close-"))
        self.assertLessEqual(len(body["orderLinkId"]), 36)
        self.assertEqual(persisted_updates[0][1]["status"], "close_requested")

    def test_duplicate_close_status_does_not_send_second_order(self) -> None:
        client = FakeCloseClient()
        duplicate_trade = {**TRADE, "status": "close_requested"}
        with patch("app.active_trade_control.get_active_trades", return_value=[duplicate_trade]):
            result = request_market_close(client, TRADE["journal_id"])

        self.assertTrue(result["ok"])
        self.assertTrue(result["duplicate"])
        self.assertEqual(result["status"], "close_requested")
        self.assertEqual(client.private_calls, [])

    def test_missing_position_stays_risk_blocked_until_exact_sync(self) -> None:
        client = FakeCloseClient(positions=[])
        persisted_updates = []

        def persist(journal_id, updates):
            persisted_updates.append(updates)
            return {"journal_id": journal_id, **updates}

        with patch("app.active_trade_control.get_active_trades", return_value=[TRADE]), patch(
            "app.active_trade_control.fetch_exact_close_result",
            return_value=(None, "exact record delayed"),
        ), patch("app.active_trade_control.update_trade_entry", side_effect=persist), patch(
            "app.active_trade_control.update_active_trade"
        ), patch("app.active_trade_control.release_active_trade") as release:
            result = request_market_close(client, TRADE["journal_id"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "close_pending_sync")
        self.assertEqual(persisted_updates[-1]["status"], "close_pending_sync")
        release.assert_not_called()
        self.assertEqual(client.private_calls, [])

    def test_ambiguous_submission_without_lookup_is_close_uncertain(self) -> None:
        client = FakeCloseClient()
        client.private_error = "network timeout"
        client.lookup_result = (False, None, "lookup unavailable")
        statuses = []

        def persist(journal_id, updates):
            statuses.append(updates.get("status"))
            return {"journal_id": journal_id, **updates}

        with patch("app.active_trade_control.get_active_trades", return_value=[TRADE]), patch(
            "app.active_trade_control.update_trade_entry", side_effect=persist
        ), patch("app.active_trade_control.update_active_trade"), patch(
            "app.active_trade_control.log_bot_event"
        ):
            result = request_market_close(client, TRADE["journal_id"])

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "CLOSE_CONFIRMATION_UNAVAILABLE")
        self.assertEqual(result["status"], "close_uncertain")
        self.assertIn("close_uncertain", statuses)


if __name__ == "__main__":
    unittest.main()

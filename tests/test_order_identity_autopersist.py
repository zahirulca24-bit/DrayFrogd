from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

import app.order_identity_autopersist as identity


class FakeRow:
    id = 1
    journal_id = "exec-abc"
    symbol = "BTCUSDT"
    order_id = None
    status = "pending_execution"
    opened_at = None
    exchange_metadata = json.dumps({"order_link_id": "df-test-link"}, separators=(",", ":"))


class FakeQuery:
    def __init__(self, row: FakeRow) -> None:
        self.row = row

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.row


class FakeSession:
    def __init__(self, row: FakeRow) -> None:
        self.row = row
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def query(self, model):
        return FakeQuery(self.row)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class OrderIdentityAutopersistTests(unittest.TestCase):
    def test_persists_accepted_order_identity_before_fill_confirmation(self) -> None:
        row = FakeRow()
        session = FakeSession(row)
        append_event = Mock()
        log_event = Mock()

        with patch.object(identity, "SessionLocal", return_value=session), patch.object(identity, "append_trade_event", append_event), patch.object(identity, "log_bot_event", log_event):
            identity._persist_accepted_order_identity(
                symbol="BTCUSDT",
                order_link_id="df-test-link",
                order_result={"orderId": "order-123", "orderLinkId": "df-test-link"},
            )

        metadata = json.loads(row.exchange_metadata)
        self.assertTrue(session.committed)
        self.assertTrue(session.closed)
        self.assertEqual(row.order_id, "order-123")
        self.assertEqual(row.status, "order_submitted")
        self.assertIsNotNone(row.opened_at)
        self.assertEqual(metadata["order_id"], "order-123")
        self.assertEqual(metadata["order_link_id"], "df-test-link")
        self.assertEqual(metadata["order_identity_source"], "accepted_order_response")
        append_event.assert_called_once()
        log_event.assert_not_called()


if __name__ == "__main__":
    unittest.main()

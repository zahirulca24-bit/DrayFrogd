from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.authoritative_state import reset_snapshot
from app.authoritative_reconciliation import reconcile_state
from app.reconciliation_persistence import _persist_exact_close


class FakeClient:
    mode = "demo"

    def safe_fetch_open_orders(self):
        return True, [], None

    def safe_fetch_positions(self):
        return True, [], None

    def safe_fetch_market_tickers(self):
        return True, [], None


class LifecyclePersistenceTests(unittest.TestCase):
    def test_exact_close_persists_all_authoritative_fields(self) -> None:
        trade = {
            "journal_id": "jrnl-1",
            "symbol": "ONDOUSDT",
            "exchange_metadata": {"existing": True},
        }
        exact = {
            "result": "profit",
            "close_reason": "exchange_transaction_log",
            "closed_at": "2026-07-16T12:30:00+00:00",
            "exit_price": 1.20,
            "realized_pnl": 10.0,
            "fees": 1.0,
            "exchange_metadata": {"close_sync": {"source": "bybit_account_transaction_log"}},
        }
        with (
            patch("app.reconciliation_persistence.update_trade_entry", return_value={"journal_id": "jrnl-1"}) as update_mock,
            patch("app.reconciliation_persistence.append_trade_event") as event_mock,
        ):
            persisted = _persist_exact_close("jrnl-1", trade, exact)

        self.assertIsNotNone(persisted)
        updates = update_mock.call_args.args[1]
        self.assertEqual(updates["status"], "closed")
        self.assertEqual(updates["result"], "profit")
        self.assertEqual(updates["exit_price"], 1.20)
        self.assertEqual(updates["realized_pnl"], 10.0)
        self.assertEqual(updates["fees"], 1.0)
        self.assertEqual(updates["closed_at"], "2026-07-16T12:30:00+00:00")
        event_mock.assert_called_once()

    def test_reconciliation_finalizes_journal_even_when_memory_trade_is_missing(self) -> None:
        reset_snapshot()
        trade = {
            "journal_id": "jrnl-restart",
            "symbol": "ONDOUSDT",
            "direction": "long",
            "execution_mode": "demo",
            "entry": 1.0,
            "stop_loss": 0.9,
            "take_profit": 1.2,
            "quantity": 10.0,
            "status": "close_pending_sync",
            "opened_at": "2026-07-16T12:00:00+00:00",
            "exchange_metadata": {},
        }
        exact = {
            "result": "profit",
            "close_reason": "exchange_transaction_log",
            "closed_at": "2026-07-16T12:30:00+00:00",
            "exit_price": 1.2,
            "realized_pnl": 1.0,
            "fees": 0.2,
            "exchange_metadata": {"close_sync": {}},
        }
        with (
            patch("app.authoritative_reconciliation.get_active_trades", return_value=[]),
            patch("app.authoritative_reconciliation._safe_open_trade_history", return_value=[trade]),
            patch("app.authoritative_reconciliation.fetch_exact_close_result", return_value=(exact, None)),
            patch("app.authoritative_reconciliation.close_trade", return_value=None),
            patch("app.authoritative_reconciliation._persist_exact_close", return_value={**trade, **exact, "status": "closed"}) as persist_mock,
            patch("app.authoritative_reconciliation.replace_active_trades"),
            patch("app.authoritative_reconciliation.release_active_trade"),
            patch("app.authoritative_reconciliation._persist_reconciliation_event"),
        ):
            result = reconcile_state(FakeClient())

        self.assertTrue(result["ok"])
        self.assertEqual(result["closed"], ["ONDOUSDT"])
        persist_mock.assert_called_once_with("jrnl-restart", trade, exact)

    def test_postgres_primary_disables_duplicate_rest_mirror(self) -> None:
        settings = SimpleNamespace(
            database_url="postgresql://primary-db",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="secret",
        )
        with (
            patch("app.journal.settings", settings),
            patch("app.journal.urlopen") as urlopen_mock,
        ):
            from app.journal import _send_supabase

            _send_supabase("bot_events", {"event_type": "test"}, upsert=False)

        urlopen_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

import unittest
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.execution_core as execution
import app.journal as journal
from app.database import Base
from app.exchange import ExchangeError


SIGNAL = {
    "symbol": "BTCUSDT",
    "strategy_name": "breakout",
    "trade_type": "scalping",
    "direction": "long",
    "entry": 100.0,
    "stop_loss": 98.0,
    "take_profit": 103.0,
    "risk_reward": 1.5,
    "detected_at": "2026-07-12T00:00:00+00:00",
    "status": "active",
}

VALIDATION = {
    "allowed": True,
    "trade_type": "scalping",
    "risk_per_trade": 0.01,
    "leverage_cap": 5.0,
    "exposure_cap": 0.30,
}

SIZING = {"allowed": True, "quantity": "1"}


class FakeClient:
    def __init__(self) -> None:
        self.order_calls = 0
        self.lookup_calls = 0
        self.protection_calls = 0
        self.close_calls = 0
        self.order_error: str | None = None
        self.lookup_result = (True, None, None)
        self.protection_error: str | None = None
        self.close_error: str | None = None

    def safe_fetch_symbol_info(self, symbol: str):
        return True, [{"symbol": symbol, "tickSize": "0.01", "qtyStep": "0.001"}], None

    def safe_fetch_wallet_balance(self):
        return True, {"totalEquity": "1000"}, None

    def safe_fetch_positions(self):
        return True, [], None

    def normalize_price(self, value: float, tick_size: str):
        return f"{value:.2f}"

    def place_market_order(self, symbol: str, side: str, qty: str, order_link_id: str | None = None):
        self.order_calls += 1
        if self.order_error:
            raise ExchangeError(self.order_error)
        return {"orderId": "order-1", "orderLinkId": order_link_id}

    def safe_fetch_order_by_link_id(self, symbol: str, order_link_id: str):
        self.lookup_calls += 1
        return self.lookup_result

    def set_trading_stop(self, symbol: str, take_profit: str, stop_loss: str):
        self.protection_calls += 1
        if self.protection_error:
            raise ExchangeError(self.protection_error)
        return {"ok": True}

    def close_position_market(self, symbol: str, side: str, qty: str):
        self.close_calls += 1
        if self.close_error:
            raise ExchangeError(self.close_error)
        return {"orderId": "close-1"}


class ExecutionIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        execution.replace_active_trades([])
        with execution._execution_lock:
            execution._closed_trades.clear()

    def _patch_common(self):
        return (
            patch("app.execution_core.can_execute", return_value=(True, "")),
            patch("app.execution_core.validate_trade", return_value=VALIDATION),
            patch("app.execution_core.calculate_position_size", return_value=SIZING),
            patch("app.execution_core.get_execution_mode", return_value="demo"),
            patch("app.execution_core.append_trade_event"),
            patch("app.execution_core.log_bot_event"),
            patch("app.execution_core.register_active_trade"),
        )

    def test_execution_key_is_deterministic_and_signal_specific(self) -> None:
        first = execution._build_execution_key(execution._normalize_signal(SIGNAL), "demo")
        second = execution._build_execution_key(execution._normalize_signal(dict(SIGNAL)), "demo")
        changed = execution._build_execution_key(execution._normalize_signal({**SIGNAL, "detected_at": "2026-07-12T00:01:00+00:00"}), "demo")

        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertLessEqual(len(execution._build_order_link_id(first)), 36)

    def test_durable_reservation_blocks_duplicate_execution_key(self) -> None:
        with NamedTemporaryFile(suffix=".db") as database_file:
            test_engine = create_engine(f"sqlite:///{database_file.name}", connect_args={"check_same_thread": False})
            TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
            Base.metadata.create_all(bind=test_engine)
            trade = {
                "symbol": "BTCUSDT",
                "strategy_name": "breakout",
                "direction": "long",
                "execution_mode": "demo",
                "entry": 100.0,
                "stop_loss": 98.0,
                "take_profit": 103.0,
                "quantity": 1.0,
                "detected_at": SIGNAL["detected_at"],
                "exchange_metadata": {},
            }
            key = "a" * 64

            with patch("app.journal.engine", test_engine), patch("app.journal.SessionLocal", TestSession), patch("app.journal._send_supabase"):
                first = journal.reserve_trade_execution(trade, key)
                second = journal.reserve_trade_execution(trade, key)

            self.assertTrue(first["reserved"])
            self.assertFalse(second["reserved"])
            self.assertEqual(first["trade"]["journal_id"], second["trade"]["journal_id"])
            self.assertEqual(second["trade"]["status"], "pending_execution")

    def test_reservation_failure_sends_no_exchange_order(self) -> None:
        client = FakeClient()
        patches = self._patch_common()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
            "app.execution_core.reserve_trade_execution", side_effect=RuntimeError("database offline")
        ):
            result = execution.execute_signal(client, SIGNAL)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "JOURNAL_RESERVATION_FAILED")
        self.assertEqual(client.order_calls, 0)

    def test_duplicate_reservation_sends_no_exchange_order(self) -> None:
        client = FakeClient()
        existing = {"journal_id": "exec-existing", "status": "active", "execution_key": "x" * 64}
        patches = self._patch_common()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
            "app.execution_core.reserve_trade_execution", return_value={"reserved": False, "trade": existing}
        ):
            result = execution.execute_signal(client, SIGNAL)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "DUPLICATE_EXECUTION")
        self.assertEqual(client.order_calls, 0)

    def test_timeout_recovers_existing_order_by_deterministic_link_id(self) -> None:
        client = FakeClient()
        client.order_error = "Request timed out"
        client.lookup_result = (True, {"orderId": "recovered-order", "orderLinkId": "df-key"}, None)
        reserved = {"journal_id": "exec-recovered", "status": "pending_execution", "execution_key": "x" * 64}
        patches = self._patch_common()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
            "app.execution_core.reserve_trade_execution", return_value={"reserved": True, "trade": reserved}
        ), patch("app.execution_core.update_trade_entry", return_value={"journal_id": "exec-recovered"}):
            result = execution.execute_signal(client, SIGNAL)

        self.assertTrue(result["ok"])
        self.assertEqual(client.order_calls, 1)
        self.assertEqual(client.lookup_calls, 1)
        self.assertEqual(client.protection_calls, 1)
        self.assertTrue(result["trade"]["exchange_metadata"]["order_recovered_after_error"])

    def test_unconfirmed_order_is_kept_uncertain_and_retry_blocked(self) -> None:
        client = FakeClient()
        client.order_error = "Network error"
        client.lookup_result = (False, None, "lookup unavailable")
        reserved = {"journal_id": "exec-uncertain", "status": "pending_execution", "execution_key": "x" * 64}
        patches = self._patch_common()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
            "app.execution_core.reserve_trade_execution", return_value={"reserved": True, "trade": reserved}
        ), patch("app.execution_core.update_trade_entry", return_value={"journal_id": "exec-uncertain"}):
            result = execution.execute_signal(client, SIGNAL)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "EXECUTION_UNCERTAIN")
        self.assertEqual(result["trade"]["status"], "execution_uncertain")
        self.assertEqual(len(execution.get_active_trades()), 1)

    def test_post_order_journal_failure_triggers_emergency_close(self) -> None:
        client = FakeClient()
        reserved = {"journal_id": "exec-journal-fail", "status": "pending_execution", "execution_key": "x" * 64}
        patches = self._patch_common()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
            "app.execution_core.reserve_trade_execution", return_value={"reserved": True, "trade": reserved}
        ), patch("app.execution_core.update_trade_entry", side_effect=RuntimeError("database write failed")):
            result = execution.execute_signal(client, SIGNAL)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "POST_ORDER_JOURNAL_FAILED")
        self.assertEqual(client.protection_calls, 1)
        self.assertEqual(client.close_calls, 1)
        self.assertEqual(result["trade"]["status"], "closed")
        self.assertEqual(len(execution.get_active_trades()), 0)


if __name__ == "__main__":
    unittest.main()

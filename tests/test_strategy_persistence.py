import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.execution_core import execute_signal, replace_active_trades
from app.journal import create_trade_entry, get_closed_trade_history, get_open_trade_history, serialize_trade_entry, update_trade_entry
from app.models import TradeJournal


class FakeExecutionClient:
    def safe_fetch_symbol_info(self, symbol: str):
        return True, [{"tickSize": "0.1", "qtyStep": "0.001"}], None

    def safe_fetch_wallet_balance(self):
        return True, {"totalEquity": "1000", "totalAvailableBalance": "500"}, None

    def safe_fetch_positions(self):
        return True, [], None

    def normalize_price(self, value: float, tick_size: str) -> str:
        return f"{float(value):.1f}"

    def place_market_order(self, symbol: str, side: str, qty: str):
        return {"orderId": "demo-order-1", "symbol": symbol, "side": side, "qty": qty}


class StrategyPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.engine = create_engine(f"sqlite:///{self.temp_db.name}", connect_args={"check_same_thread": False})
        self.session_local = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        replace_active_trades([])

        self.patches = [
            patch("app.journal.engine", self.engine),
            patch("app.journal.SessionLocal", self.session_local),
            patch("app.journal._send_supabase", return_value=None),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self) -> None:
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.engine.dispose()
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)
        replace_active_trades([])

    def test_strategy_name_persists_on_opened_trade(self) -> None:
        signal = {
            "symbol": "BTCUSDT",
            "strategy_name": "ema_pullback",
            "trade_type": "scalping",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 95.0,
            "take_profit": 107.5,
            "detected_at": datetime.now(UTC).isoformat(),
            "status": "active",
        }

        with (
            patch("app.execution_core.can_execute", return_value=(True, None)),
            patch("app.execution_core.validate_trade", return_value={"allowed": True, "trade_type": "scalping", "risk_per_trade": 0.01, "leverage_cap": 5, "exposure_cap": 0.3}),
            patch("app.execution_core.calculate_position_size", return_value={"allowed": True, "quantity": "1", "notional": 100.0}),
            patch("app.execution_core.get_execution_mode", return_value="demo"),
            patch("app.execution_core._attach_protection_with_retry", return_value=None),
            patch("app.execution_core.register_active_trade", return_value=None),
        ):
            result = execute_signal(FakeExecutionClient(), signal, auto_triggered=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["trade"]["strategy_name"], "ema_pullback")
        self.assertEqual(result["trade"]["strategy"], "ema_pullback")

        open_trades = get_open_trade_history()
        self.assertEqual(len(open_trades), 1)
        self.assertEqual(open_trades[0]["strategy_name"], "ema_pullback")
        self.assertEqual(open_trades[0]["strategy"], "ema_pullback")

    def test_strategy_name_persists_after_close_and_journal_save(self) -> None:
        trade = {
            "journal_id": "jrnl-close-1",
            "symbol": "BTCUSDT",
            "strategy_name": "ema_pullback",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 95.0,
            "take_profit": 107.5,
            "quantity": "1",
            "status": "active",
            "opened_at": datetime.now(UTC).isoformat(),
            "exchange_metadata": {"strategy_name": "ema_pullback"},
        }
        create_trade_entry(trade)

        update_trade_entry(
            "jrnl-close-1",
            {
                "status": "closed",
                "result": "tp",
                "closed_at": datetime.now(UTC).isoformat(),
                "exchange_metadata": {"strategy_name": "ema_pullback", "strategy": "ema_pullback"},
            },
        )

        closed_trades = get_closed_trade_history()
        self.assertEqual(len(closed_trades), 1)
        self.assertEqual(closed_trades[0]["strategy_name"], "ema_pullback")
        self.assertEqual(closed_trades[0]["strategy"], "ema_pullback")

    def test_legacy_strategy_records_still_load(self) -> None:
        session = self.session_local()
        try:
            session.add(
                TradeJournal(
                    journal_id="legacy-1",
                    symbol="BTCUSDT",
                    direction="long",
                    execution_mode="demo",
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=107.5,
                    quantity=1.0,
                    strategy_name=None,
                    status="closed",
                    opened_at=datetime.now(UTC).isoformat(),
                    exchange_metadata=json.dumps({"strategy": "ema_pullback"}),
                )
            )
            session.commit()
            row = session.query(TradeJournal).filter(TradeJournal.journal_id == "legacy-1").first()
            payload = serialize_trade_entry(row)
        finally:
            session.close()

        self.assertEqual(payload["strategy_name"], "ema_pullback")
        self.assertEqual(payload["strategy"], "ema_pullback")

    def test_missing_strategy_field_falls_back_to_unknown(self) -> None:
        session = self.session_local()
        try:
            session.add(
                TradeJournal(
                    journal_id="legacy-unknown-1",
                    symbol="BTCUSDT",
                    direction="short",
                    execution_mode="demo",
                    entry_price=100.0,
                    stop_loss=105.0,
                    take_profit=92.5,
                    quantity=1.0,
                    strategy_name=None,
                    status="closed",
                    opened_at=datetime.now(UTC).isoformat(),
                    exchange_metadata=json.dumps({}),
                )
            )
            session.commit()
            row = session.query(TradeJournal).filter(TradeJournal.journal_id == "legacy-unknown-1").first()
            payload = serialize_trade_entry(row)
        finally:
            session.close()

        self.assertEqual(payload["strategy_name"], "unknown")
        self.assertEqual(payload["strategy"], "unknown")


if __name__ == "__main__":
    unittest.main()

import unittest
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from sqlalchemy import create_engine, inspect, text

from app.execution import _calculate_realized_pnl
from app.journal import _ensure_trade_journal_columns, serialize_trade_entry
from app.models import TradeJournal


class TradePnlPersistenceTests(unittest.TestCase):
    def test_long_realized_pnl_is_net_of_fees(self) -> None:
        trade = {
            "direction": "long",
            "entry": 100.0,
            "quantity": 2.0,
        }

        self.assertEqual(_calculate_realized_pnl(trade, exit_price=110.0, fees=1.0), 19.0)

    def test_short_realized_pnl_is_net_of_fees(self) -> None:
        trade = {
            "direction": "short",
            "entry": 100.0,
            "remaining_quantity": 2.0,
        }

        self.assertEqual(_calculate_realized_pnl(trade, exit_price=90.0, fees=1.0), 19.0)

    def test_invalid_trade_does_not_fabricate_realized_pnl(self) -> None:
        trade = {
            "direction": "long",
            "entry": 100.0,
            "quantity": 0,
        }

        self.assertIsNone(_calculate_realized_pnl(trade, exit_price=110.0, fees=0.0))

    def test_serializer_exposes_financial_close_fields(self) -> None:
        row = TradeJournal(
            journal_id="jrnl-test",
            symbol="BTCUSDT",
            direction="long",
            execution_mode="demo",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            quantity=2.0,
            strategy_name="breakout",
            status="closed",
            result="tp",
            close_reason="TAKE_PROFIT",
            exit_price=110.0,
            realized_pnl=19.0,
            fees=1.0,
            exchange_metadata="{}",
        )

        payload = serialize_trade_entry(row)

        self.assertEqual(payload["strategy_name"], "breakout")
        self.assertEqual(payload["close_reason"], "TAKE_PROFIT")
        self.assertEqual(payload["exit_price"], 110.0)
        self.assertEqual(payload["realized_pnl"], 19.0)
        self.assertEqual(payload["fees"], 1.0)

    def test_legacy_sqlite_table_receives_new_columns(self) -> None:
        with NamedTemporaryFile(suffix=".db") as database_file:
            legacy_engine = create_engine(f"sqlite:///{database_file.name}")
            with legacy_engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        CREATE TABLE trade_journal (
                            id INTEGER PRIMARY KEY,
                            journal_id VARCHAR(64) NOT NULL,
                            symbol VARCHAR(32) NOT NULL,
                            direction VARCHAR(16) NOT NULL,
                            execution_mode VARCHAR(16) NOT NULL,
                            entry_price FLOAT NOT NULL,
                            stop_loss FLOAT NOT NULL,
                            take_profit FLOAT NOT NULL,
                            status VARCHAR(32) NOT NULL
                        )
                        """
                    )
                )

            with patch("app.journal.engine", legacy_engine):
                _ensure_trade_journal_columns()

            columns = {column["name"] for column in inspect(legacy_engine).get_columns("trade_journal")}
            self.assertTrue({"strategy_name", "close_reason", "exit_price", "realized_pnl", "fees"}.issubset(columns))


if __name__ == "__main__":
    unittest.main()

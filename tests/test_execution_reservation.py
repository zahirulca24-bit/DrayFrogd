from __future__ import annotations

import unittest
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.execution_reservation import reserve_execution_capacity
from app.models import RiskRuntimeState


class AtomicExecutionReservationTests(unittest.TestCase):
    def test_risk_capacity_and_active_trade_slot_are_reserved_atomically(self) -> None:
        with NamedTemporaryFile(suffix=".db") as database_file:
            test_engine = create_engine(
                f"sqlite:///{database_file.name}",
                connect_args={"check_same_thread": False},
            )
            TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
            Base.metadata.create_all(bind=test_engine)

            db = TestSession()
            try:
                db.add(
                    RiskRuntimeState(
                        id=1,
                        trades_day="2026-07-12",
                        active_symbols="[]",
                        symbol_cooldowns="{}",
                        day_start_equity=1000.0,
                        live_risk=0.0,
                        base_risk_pool=50.0,
                        effective_risk_pool=50.0,
                        available_risk=50.0,
                        active_trade_count=0,
                        circuit_breaker_active=False,
                    )
                )
                db.commit()
            finally:
                db.close()

            first_trade = self._trade("BTCUSDT")
            second_trade = self._trade("ETHUSDT")

            with (
                patch("app.execution_reservation.SessionLocal", TestSession),
                patch("app.journal.SessionLocal", TestSession),
                patch("app.journal.engine", test_engine),
            ):
                first = reserve_execution_capacity(
                    first_trade,
                    "a" * 64,
                    required_risk=20.0,
                    max_active_trades=5,
                )
                second = reserve_execution_capacity(
                    second_trade,
                    "b" * 64,
                    required_risk=40.0,
                    max_active_trades=5,
                )

            self.assertTrue(first["reserved"])
            self.assertFalse(second["reserved"])
            self.assertEqual(second["reason"], "DYNAMIC_RISK_CAPACITY_EXCEEDED")
            self.assertEqual(second["available_risk"], 30.0)

            db = TestSession()
            try:
                state = db.query(RiskRuntimeState).filter(RiskRuntimeState.id == 1).one()
                self.assertEqual(state.available_risk, 30.0)
                self.assertEqual(state.live_risk, 20.0)
                self.assertEqual(state.active_trade_count, 1)
                self.assertIn("BTCUSDT", state.active_symbols)
            finally:
                db.close()

    def test_same_symbol_is_blocked_even_for_different_execution_key(self) -> None:
        with NamedTemporaryFile(suffix=".db") as database_file:
            test_engine = create_engine(
                f"sqlite:///{database_file.name}",
                connect_args={"check_same_thread": False},
            )
            TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
            Base.metadata.create_all(bind=test_engine)

            db = TestSession()
            try:
                db.add(
                    RiskRuntimeState(
                        id=1,
                        trades_day="2026-07-12",
                        active_symbols="[]",
                        symbol_cooldowns="{}",
                        day_start_equity=1000.0,
                        live_risk=0.0,
                        base_risk_pool=50.0,
                        effective_risk_pool=50.0,
                        available_risk=50.0,
                        active_trade_count=0,
                        circuit_breaker_active=False,
                    )
                )
                db.commit()
            finally:
                db.close()

            with (
                patch("app.execution_reservation.SessionLocal", TestSession),
                patch("app.journal.SessionLocal", TestSession),
                patch("app.journal.engine", test_engine),
            ):
                first = reserve_execution_capacity(
                    self._trade("BTCUSDT"),
                    "c" * 64,
                    required_risk=20.0,
                    max_active_trades=5,
                )
                duplicate_symbol = reserve_execution_capacity(
                    self._trade("BTCUSDT"),
                    "d" * 64,
                    required_risk=20.0,
                    max_active_trades=5,
                )

            self.assertTrue(first["reserved"])
            self.assertFalse(duplicate_symbol["reserved"])
            self.assertEqual(duplicate_symbol["reason"], "SYMBOL_ALREADY_ACTIVE")

    @staticmethod
    def _trade(symbol: str) -> dict:
        return {
            "symbol": symbol,
            "strategy_name": "breakout",
            "direction": "long",
            "execution_mode": "demo",
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": 103.0,
            "quantity": 10.0,
            "detected_at": "2026-07-12T00:00:00+00:00",
            "exchange_metadata": {},
        }


if __name__ == "__main__":
    unittest.main()

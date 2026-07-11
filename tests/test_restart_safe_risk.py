import json
import unittest
from datetime import UTC, datetime, timedelta
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.risk as risk
from app.database import Base
from app.models import RiskRuntimeState, TradeJournal


RISK_SETTINGS = {
    "risk_per_trade": 0.01,
    "leverage_cap": 5.0,
    "exposure_cap": 0.30,
    "max_open_trades": 3,
    "max_daily_trades": 8,
}


def make_trade(*, journal_id: str, symbol: str, status: str, opened_at: str) -> TradeJournal:
    return TradeJournal(
        journal_id=journal_id,
        symbol=symbol,
        direction="long",
        execution_mode="demo",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit=103.0,
        quantity=1.0,
        strategy_name="breakout",
        status=status,
        opened_at=opened_at,
        exchange_metadata="{}",
    )


class RestartSafeRiskTests(unittest.TestCase):
    def tearDown(self) -> None:
        with risk._risk_lock:
            risk._active_symbols.clear()
            risk._trades_today = 0
            risk._trades_day = None
            risk._cooldown_until = None
            risk._state_loaded = False

    def test_bdt_day_changes_at_1800_utc(self) -> None:
        self.assertEqual(risk._bdt_day(datetime(2026, 7, 11, 17, 59, tzinfo=UTC)), "2026-07-11")
        self.assertEqual(risk._bdt_day(datetime(2026, 7, 11, 18, 0, tzinfo=UTC)), "2026-07-12")

    def test_daily_counter_resets_on_bdt_midnight(self) -> None:
        with risk._risk_lock:
            risk._trades_day = "2026-07-11"
            risk._trades_today = 4
            changed = risk._reset_daily_state_if_needed(datetime(2026, 7, 11, 18, 0, tzinfo=UTC))

        self.assertTrue(changed)
        self.assertEqual(risk._trades_day, "2026-07-12")
        self.assertEqual(risk._trades_today, 0)

    def test_restore_uses_open_journal_and_bdt_daily_count(self) -> None:
        now = datetime(2026, 7, 12, 0, 30, tzinfo=UTC)
        with NamedTemporaryFile(suffix=".db") as database_file:
            test_engine = create_engine(f"sqlite:///{database_file.name}", connect_args={"check_same_thread": False})
            TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
            Base.metadata.create_all(bind=test_engine)

            db = TestSession()
            try:
                db.add_all(
                    [
                        make_trade(journal_id="open-today", symbol="BTCUSDT", status="active", opened_at="2026-07-11T18:10:00+00:00"),
                        make_trade(journal_id="closed-today", symbol="ETHUSDT", status="closed", opened_at="2026-07-11T19:00:00+00:00"),
                        make_trade(journal_id="open-yesterday", symbol="XRPUSDT", status="closed", opened_at="2026-07-11T17:50:00+00:00"),
                    ]
                )
                db.add(
                    RiskRuntimeState(
                        id=1,
                        trades_day="2026-07-12",
                        trades_today=1,
                        active_symbols='["STALEUSDT"]',
                        cooldown_until=now + timedelta(minutes=10),
                    )
                )
                db.commit()
            finally:
                db.close()

            with patch("app.risk.engine", test_engine), patch("app.risk.SessionLocal", TestSession):
                with risk._risk_lock:
                    risk._state_loaded = False
                    risk._active_symbols.clear()
                    risk._trades_today = 0
                    risk._trades_day = None
                    risk._cooldown_until = None

                restored = risk.restore_risk_state(now)

                self.assertEqual(restored["active_symbols"], ["BTCUSDT"])
                self.assertEqual(restored["trades_today"], 2)
                self.assertEqual(restored["trades_day"], "2026-07-12")

                signal = {
                    "symbol": "BTCUSDT",
                    "direction": "long",
                    "entry": 100.0,
                    "stop_loss": 98.0,
                    "take_profit": 103.0,
                    "risk_reward": 1.5,
                    "status": "active",
                }
                with patch("app.risk.get_risk_settings", return_value=RISK_SETTINGS):
                    validation = risk.validate_trade(signal)
                self.assertFalse(validation["allowed"])
                self.assertEqual(validation["reason"], "Cooldown active after loss")

                risk.release_active_trade("BTCUSDT")
                db = TestSession()
                try:
                    row = db.query(RiskRuntimeState).filter(RiskRuntimeState.id == 1).one()
                    self.assertEqual(json.loads(row.active_symbols), [])
                    self.assertEqual(row.trades_today, 2)
                    self.assertEqual(row.trades_day, "2026-07-12")
                finally:
                    db.close()

    def test_expired_cooldown_is_removed_on_restore(self) -> None:
        now = datetime(2026, 7, 12, 0, 30, tzinfo=UTC)
        with NamedTemporaryFile(suffix=".db") as database_file:
            test_engine = create_engine(f"sqlite:///{database_file.name}", connect_args={"check_same_thread": False})
            TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
            Base.metadata.create_all(bind=test_engine)

            db = TestSession()
            try:
                db.add(RiskRuntimeState(id=1, trades_day="2026-07-12", trades_today=0, active_symbols="[]", cooldown_until=now - timedelta(minutes=1)))
                db.commit()
            finally:
                db.close()

            with patch("app.risk.engine", test_engine), patch("app.risk.SessionLocal", TestSession):
                with risk._risk_lock:
                    risk._state_loaded = False
                restored = risk.restore_risk_state(now)
                self.assertIsNone(restored["cooldown_until"])


if __name__ == "__main__":
    unittest.main()

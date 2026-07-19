import unittest
from datetime import UTC, datetime, timedelta
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.risk as risk
from app.database import Base
from app.models import RiskRuntimeState, TradeJournal


def make_trade(
    *,
    journal_id: str,
    symbol: str,
    status: str,
    opened_at: str,
    closed_at: str | None = None,
    realized_pnl: float | None = None,
    stop_loss: float = 98.0,
    metadata: str = "{}",
) -> TradeJournal:
    return TradeJournal(
        journal_id=journal_id,
        symbol=symbol,
        direction="long",
        execution_mode="demo",
        entry_price=100.0,
        stop_loss=stop_loss,
        take_profit=103.0,
        quantity=1.0,
        strategy_name="breakout",
        status=status,
        opened_at=opened_at,
        closed_at=closed_at,
        realized_pnl=realized_pnl,
        exchange_metadata=metadata,
    )


class RestartSafeRiskTests(unittest.TestCase):
    def test_bdt_day_changes_at_1800_utc(self) -> None:
        self.assertEqual(risk._bdt_day(datetime(2026, 7, 11, 17, 59, tzinfo=UTC)), "2026-07-11")
        self.assertEqual(risk._bdt_day(datetime(2026, 7, 11, 18, 0, tzinfo=UTC)), "2026-07-12")

    def test_restore_uses_journal_as_authority_after_restart(self) -> None:
        now = datetime(2026, 7, 12, 0, 30, tzinfo=UTC)
        with NamedTemporaryFile(suffix=".db") as database_file:
            test_engine = create_engine(
                f"sqlite:///{database_file.name}",
                connect_args={"check_same_thread": False},
            )
            TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
            Base.metadata.create_all(bind=test_engine)

            db = TestSession()
            try:
                db.add_all(
                    [
                        make_trade(
                            journal_id="open-today",
                            symbol="BTCUSDT",
                            status="active",
                            opened_at="2026-07-11T18:10:00+00:00",
                        ),
                        make_trade(
                            journal_id="closed-profit",
                            symbol="ETHUSDT",
                            status="closed",
                            opened_at="2026-07-11T19:00:00+00:00",
                            closed_at="2026-07-11T20:00:00+00:00",
                            realized_pnl=10.0,
                        ),
                        make_trade(
                            journal_id="closed-yesterday",
                            symbol="XRPUSDT",
                            status="closed",
                            opened_at="2026-07-11T17:50:00+00:00",
                            closed_at="2026-07-11T17:55:00+00:00",
                            realized_pnl=-5.0,
                        ),
                    ]
                )
                db.add(
                    RiskRuntimeState(
                        id=1,
                        trades_day="2026-07-12",
                        trades_today=1,
                        active_symbols='["STALEUSDT"]',
                        symbol_cooldowns="{}",
                        day_start_equity=1000.0,
                    )
                )
                db.commit()
            finally:
                db.close()

            with patch("app.risk.engine", test_engine), patch("app.risk.SessionLocal", TestSession):
                restored = risk.restore_risk_state(now=now, account_equity=1000.0)

            self.assertEqual(restored["active_symbols"], ["BTCUSDT"])
            self.assertEqual(restored["active_trade_count"], 1)
            self.assertEqual(restored["trades_today"], 2)
            self.assertEqual(restored["trades_day"], "2026-07-12")
            self.assertEqual(restored["realized_pnl_today"], 10.0)
            self.assertEqual(restored["live_risk"], 2.0)
            self.assertEqual(restored["base_risk_pool"], 250.0)
            self.assertEqual(restored["effective_risk_pool"], 260.0)
            self.assertEqual(restored["available_risk"], 258.0)

    def test_bdt_midnight_resets_daily_financial_state(self) -> None:
        previous_day = datetime(2026, 7, 11, 17, 59, tzinfo=UTC)
        new_day = datetime(2026, 7, 11, 18, 0, tzinfo=UTC)
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
                        trades_day=risk._bdt_day(previous_day),
                        trades_today=8,
                        active_symbols="[]",
                        symbol_cooldowns="{}",
                        day_start_equity=1000.0,
                        realized_pnl_today=-50.0,
                        circuit_breaker_active=True,
                        circuit_breaker_reason="old day",
                    )
                )
                db.commit()
            finally:
                db.close()

            with patch("app.risk.engine", test_engine), patch("app.risk.SessionLocal", TestSession):
                restored = risk.restore_risk_state(now=new_day, account_equity=900.0)

            self.assertEqual(restored["trades_day"], "2026-07-12")
            self.assertEqual(restored["trades_today"], 0)
            self.assertEqual(restored["day_start_equity"], 900.0)
            self.assertEqual(restored["realized_pnl_today"], 0.0)
            self.assertFalse(restored["circuit_breaker_active"])
            self.assertEqual(restored["base_risk_pool"], 225.0)

    def test_expired_symbol_cooldown_is_removed_on_restore(self) -> None:
        now = datetime(2026, 7, 12, 0, 30, tzinfo=UTC)
        expired = now - timedelta(minutes=1)
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
                        symbol_cooldowns=f'{{"BTCUSDT":"{expired.isoformat()}"}}',
                        cooldown_until=expired,
                        day_start_equity=1000.0,
                    )
                )
                db.commit()
            finally:
                db.close()

            with patch("app.risk.engine", test_engine), patch("app.risk.SessionLocal", TestSession):
                restored = risk.restore_risk_state(now=now, account_equity=1000.0)

            self.assertEqual(restored["symbol_cooldowns"], {})
            self.assertIsNone(restored["cooldown_until"])

    def test_account_equity_drawdown_trips_daily_loss_breaker_before_journal_sync(self) -> None:
        now = datetime(2026, 7, 12, 0, 30, tzinfo=UTC)
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
                        realized_pnl_today=0.0,
                    )
                )
                db.commit()
            finally:
                db.close()

            with (
                patch("app.risk.engine", test_engine),
                patch("app.risk.SessionLocal", TestSession),
                patch("app.risk.stop_bot") as stop_bot,
                patch("app.risk.log_bot_event"),
            ):
                restored = risk.restore_risk_state(now=now, account_equity=940.0)

            self.assertTrue(restored["circuit_breaker_active"])
            self.assertIn("account equity drawdown", restored["circuit_breaker_reason"])
            self.assertEqual(restored["current_account_equity"], 940.0)
            self.assertEqual(restored["equity_drawdown_today"], -60.0)
            stop_bot.assert_called_once()


if __name__ == "__main__":
    unittest.main()

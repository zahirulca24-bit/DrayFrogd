from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.background_worker import _is_expected_execution_block
from app.bot_controls import DEFAULT_RISK_SETTINGS
from app.database import Base
from app.execution_reservation import reserve_execution_capacity
from app.models import RiskRuntimeState, TradeJournal
from app.risk import refresh_risk_state, validate_trade


class TradeChurnGuardTests(unittest.TestCase):
    def test_policy_locks_daily_execution_limit_to_eight(self) -> None:
        self.assertEqual(DEFAULT_RISK_SETTINGS["max_daily_trades"], 8)

    def test_preflight_blocks_ninth_trade(self) -> None:
        state = {
            "circuit_breaker_active": False,
            "circuit_breaker_reason": None,
            "day_start_equity": 1000.0,
            "symbol_cooldowns": {},
            "active_symbols": [],
            "active_trade_count": 0,
            "available_risk": 50.0,
            "live_risk": 0.0,
            "base_risk_pool": 50.0,
            "effective_risk_pool": 50.0,
            "trades_today": 8,
            "max_trades_per_day": 8,
        }
        with patch("app.risk.refresh_risk_state", return_value=state):
            result = validate_trade(self._signal(), account_equity=1000.0)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "DAILY_TRADE_LIMIT_REACHED")

    def test_atomic_reservation_cannot_exceed_daily_limit(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        with self._database(trades_today=7, available_risk=100.0) as resources:
            TestSession, test_engine = resources
            with self._reservation_patches(TestSession, test_engine):
                first = reserve_execution_capacity(
                    self._trade("BTCUSDT"),
                    "a" * 64,
                    required_risk=20.0,
                    max_active_trades=5,
                    max_daily_trades=8,
                    reentry_cooldown_minutes=30,
                    now=now,
                )
                ninth = reserve_execution_capacity(
                    self._trade("ETHUSDT"),
                    "b" * 64,
                    required_risk=20.0,
                    max_active_trades=5,
                    max_daily_trades=8,
                    reentry_cooldown_minutes=30,
                    now=now,
                )
            self.assertTrue(first["reserved"])
            self.assertFalse(ninth["reserved"])
            self.assertEqual(ninth["reason"], "DAILY_TRADE_LIMIT_REACHED")

    def test_recent_terminal_close_blocks_same_symbol_reentry(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        with self._database(trades_today=1, available_risk=100.0) as resources:
            TestSession, test_engine = resources
            self._add_closed_trade(TestSession, "BTCUSDT", now - timedelta(minutes=10))
            with self._reservation_patches(TestSession, test_engine):
                result = reserve_execution_capacity(
                    self._trade("BTCUSDT"),
                    "c" * 64,
                    required_risk=20.0,
                    max_active_trades=5,
                    max_daily_trades=8,
                    reentry_cooldown_minutes=30,
                    now=now,
                )
            self.assertFalse(result["reserved"])
            self.assertEqual(result["reason"], "SYMBOL_REENTRY_COOLDOWN")
            self.assertIn("cooldown_until", result)

    def test_symbol_can_reenter_after_cooldown_expiry(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        with self._database(trades_today=1, available_risk=100.0) as resources:
            TestSession, test_engine = resources
            self._add_closed_trade(TestSession, "BTCUSDT", now - timedelta(minutes=31))
            with self._reservation_patches(TestSession, test_engine):
                result = reserve_execution_capacity(
                    self._trade("BTCUSDT"),
                    "d" * 64,
                    required_risk=20.0,
                    max_active_trades=5,
                    max_daily_trades=8,
                    reentry_cooldown_minutes=30,
                    now=now,
                )
            self.assertTrue(result["reserved"])

    def test_execution_failed_row_does_not_consume_daily_slot_after_refresh(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        with self._database(trades_today=1, available_risk=50.0) as resources:
            TestSession, test_engine = resources
            db = TestSession()
            try:
                db.add(
                    TradeJournal(
                        journal_id="failed-row",
                        execution_key="f" * 64,
                        symbol="BTCUSDT",
                        direction="long",
                        execution_mode="demo",
                        entry_price=100.0,
                        stop_loss=99.0,
                        take_profit=101.5,
                        quantity=1.0,
                        strategy_name="ema_pullback",
                        status="closed",
                        result="execution_failed",
                        detected_at=now.isoformat(),
                        opened_at=None,
                        closed_at=now.isoformat(),
                    )
                )
                db.commit()
            finally:
                db.close()
            with (
                patch("app.risk.SessionLocal", TestSession),
                patch("app.risk.engine", test_engine),
                patch("app.risk._ensure_risk_runtime_columns"),
            ):
                state = refresh_risk_state(account_equity=1000.0, now=now)
            self.assertEqual(state["trades_today"], 0)

    def test_expected_guard_blocks_are_not_execution_failures(self) -> None:
        for code in (
            "DUPLICATE_EXECUTION",
            "SYMBOL_ALREADY_ACTIVE",
            "DAILY_TRADE_LIMIT_REACHED",
            "SYMBOL_REENTRY_COOLDOWN",
        ):
            with self.subTest(code=code):
                self.assertTrue(_is_expected_execution_block(code))
        self.assertFalse(_is_expected_execution_block("ORDER_NOT_ACCEPTED"))

    @staticmethod
    def _signal() -> dict:
        return {
            "symbol": "BTCUSDT",
            "strategy_name": "ema_pullback",
            "trade_type": "scalping",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 99.0,
            "take_profit": 101.5,
            "risk_reward": 1.5,
            "status": "active",
        }

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
            "detected_at": "2026-07-14T11:59:00+00:00",
            "exchange_metadata": {},
        }

    @staticmethod
    def _add_closed_trade(TestSession, symbol: str, closed_at: datetime) -> None:
        db = TestSession()
        try:
            db.add(
                TradeJournal(
                    journal_id=f"closed-{symbol}-{int(closed_at.timestamp())}",
                    execution_key=(symbol.lower() + "0" * 64)[:64],
                    symbol=symbol,
                    direction="long",
                    execution_mode="demo",
                    entry_price=100.0,
                    stop_loss=99.0,
                    take_profit=101.5,
                    quantity=1.0,
                    strategy_name="ema_pullback",
                    status="closed",
                    result="loss",
                    detected_at=(closed_at - timedelta(minutes=10)).isoformat(),
                    opened_at=(closed_at - timedelta(minutes=9)).isoformat(),
                    closed_at=closed_at.isoformat(),
                )
            )
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _reservation_patches(TestSession, test_engine):
        return _PatchGroup(
            patch("app.execution_reservation.SessionLocal", TestSession),
            patch("app.journal.SessionLocal", TestSession),
            patch("app.journal.engine", test_engine),
        )

    @staticmethod
    def _database(*, trades_today: int, available_risk: float):
        return _TemporaryDatabase(trades_today=trades_today, available_risk=available_risk)


class _PatchGroup:
    def __init__(self, *patchers):
        self.patchers = patchers

    def __enter__(self):
        for patcher in self.patchers:
            patcher.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        for patcher in reversed(self.patchers):
            patcher.stop()


class _TemporaryDatabase:
    def __init__(self, *, trades_today: int, available_risk: float):
        self.trades_today = trades_today
        self.available_risk = available_risk
        self.file = None
        self.engine = None
        self.Session = None

    def __enter__(self):
        self.file = NamedTemporaryFile(suffix=".db")
        self.engine = create_engine(
            f"sqlite:///{self.file.name}",
            connect_args={"check_same_thread": False},
        )
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        db = self.Session()
        try:
            db.add(
                RiskRuntimeState(
                    id=1,
                    trades_day="2026-07-14",
                    trades_today=self.trades_today,
                    active_symbols="[]",
                    symbol_cooldowns="{}",
                    day_start_equity=1000.0,
                    live_risk=0.0,
                    base_risk_pool=100.0,
                    effective_risk_pool=100.0,
                    available_risk=self.available_risk,
                    active_trade_count=0,
                    circuit_breaker_active=False,
                )
            )
            db.commit()
        finally:
            db.close()
        return self.Session, self.engine

    def __exit__(self, exc_type, exc, tb):
        if self.engine is not None:
            self.engine.dispose()
        if self.file is not None:
            self.file.close()


if __name__ == "__main__":
    unittest.main()

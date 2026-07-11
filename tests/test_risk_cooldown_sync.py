from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import RiskRuntimeState, TradeJournal
from app.risk_cooldown_sync import sync_loss_cooldowns


class RiskCooldownSyncTests(unittest.TestCase):
    def test_only_recent_exact_negative_realized_pnl_creates_cooldown(self) -> None:
        now = datetime(2026, 7, 12, 6, 0, tzinfo=UTC)
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
                        self._trade(
                            journal_id="recent-loss",
                            symbol="BTCUSDT",
                            realized_pnl=-10.0,
                            closed_at=(now - timedelta(minutes=10)).isoformat(),
                        ),
                        self._trade(
                            journal_id="recent-profit",
                            symbol="ETHUSDT",
                            realized_pnl=10.0,
                            closed_at=(now - timedelta(minutes=5)).isoformat(),
                        ),
                        self._trade(
                            journal_id="old-loss",
                            symbol="XRPUSDT",
                            realized_pnl=-5.0,
                            closed_at=(now - timedelta(minutes=31)).isoformat(),
                        ),
                    ]
                )
                db.commit()
            finally:
                db.close()

            with (
                patch("app.risk_cooldown_sync.SessionLocal", TestSession),
                patch("app.risk.SessionLocal", TestSession),
                patch("app.risk.engine", test_engine),
            ):
                result = sync_loss_cooldowns(now=now)

            self.assertEqual(result["applied_count"], 1)
            self.assertEqual(result["applied"][0]["symbol"], "BTCUSDT")

            db = TestSession()
            try:
                state = db.query(RiskRuntimeState).filter(RiskRuntimeState.id == 1).one()
                cooldowns = json.loads(state.symbol_cooldowns)
            finally:
                db.close()

            self.assertEqual(set(cooldowns), {"BTCUSDT"})
            expected = now + timedelta(minutes=20)
            actual = datetime.fromisoformat(cooldowns["BTCUSDT"])
            self.assertEqual(actual, expected)

    @staticmethod
    def _trade(*, journal_id: str, symbol: str, realized_pnl: float, closed_at: str) -> TradeJournal:
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
            status="closed",
            result="loss" if realized_pnl < 0 else "profit",
            realized_pnl=realized_pnl,
            closed_at=closed_at,
            exchange_metadata="{}",
        )


if __name__ == "__main__":
    unittest.main()

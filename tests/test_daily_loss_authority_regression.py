import unittest
from datetime import UTC, datetime, timedelta
from tempfile import NamedTemporaryFile
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import RiskRuntimeState, TradeJournal
import app.risk as risk
import app.batch1_execution_safety as safety


def make_test_trade(
    *,
    journal_id: str,
    symbol: str,
    status: str,
    closed_at: str | None = None,
    realized_pnl: float | None = None,
    order_id: str | None = None,
    execution_key: str | None = None,
    exchange_metadata: str = "{}",
) -> TradeJournal:
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
        closed_at=closed_at,
        realized_pnl=realized_pnl,
        order_id=order_id,
        execution_key=execution_key,
        exchange_metadata=exchange_metadata,
    )


class DailyLossAuthorityRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        # Create an isolated temporary database for each test
        self.db_file = NamedTemporaryFile(suffix=".db", delete=False)
        self.engine = create_engine(
            f"sqlite:///{self.db_file.name}",
            connect_args={"check_same_thread": False},
        )
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        self.patches = [
            patch("app.risk.engine", self.engine),
            patch("app.risk.SessionLocal", self.Session),
            patch("app.batch1_execution_safety.SessionLocal", self.Session),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.engine.dispose()
        self.db_file.close()

    def test_1_positive_pnl_does_not_trip_hard_stop(self) -> None:
        """1. Positive current-day account net does not trip the hard stop."""
        db = self.Session()
        now = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
        db.add(RiskRuntimeState(id=1, trades_day="2026-07-12", day_start_equity=1000.0))
        db.add(make_test_trade(
            journal_id="trade-1",
            symbol="BTCUSDT",
            status="closed",
            closed_at="2026-07-12T15:00:00+06:00",  # BDT
            realized_pnl=50.0,
        ))
        db.commit()
        db.close()

        state = risk.restore_risk_state(now=now, account_equity=1000.0)
        self.assertFalse(state["circuit_breaker_active"])
        self.assertEqual(state["realized_pnl_today"], 50.0)

    def test_2_genuine_loss_trips_hard_stop(self) -> None:
        """2. Genuine current-day loss beyond 5% trips the hard stop."""
        db = self.Session()
        now = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
        db.add(RiskRuntimeState(id=1, trades_day="2026-07-12", day_start_equity=1000.0))
        db.add(make_test_trade(
            journal_id="trade-1",
            symbol="BTCUSDT",
            status="closed",
            closed_at="2026-07-12T15:00:00+06:00",  # BDT
            realized_pnl=-55.0,  # > 50.0 loss limit
        ))
        db.commit()
        db.close()

        with patch("app.risk.stop_bot") as mock_stop:
            state = risk.restore_risk_state(now=now, account_equity=1000.0)
        self.assertTrue(state["circuit_breaker_active"])
        self.assertIn("Daily net realized loss limit reached", state["circuit_breaker_reason"])
        mock_stop.assert_called_once()

    def test_3_historical_losses_excluded(self) -> None:
        """3. Historical losses from previous days are excluded."""
        db = self.Session()
        now = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
        db.add(RiskRuntimeState(id=1, trades_day="2026-07-12", day_start_equity=1000.0))
        # Yesterday's trade loss
        db.add(make_test_trade(
            journal_id="trade-1",
            symbol="BTCUSDT",
            status="closed",
            closed_at="2026-07-11T15:00:00+06:00",  # Yesterday BDT
            realized_pnl=-100.0,
        ))
        db.commit()
        db.close()

        state = risk.restore_risk_state(now=now, account_equity=1000.0)
        self.assertFalse(state["circuit_breaker_active"])
        self.assertEqual(state["realized_pnl_today"], 0.0)

    def test_4_utc_bdt_boundary_records_assigned_correctly(self) -> None:
        """4. UTC/BDT boundary records are assigned to the correct operational day."""
        # 18:00 UTC on July 11 is 00:00 BDT on July 12.
        t1 = datetime(2026, 7, 11, 17, 59, tzinfo=UTC) # BDT: July 11, 23:59
        t2 = datetime(2026, 7, 11, 18, 1, tzinfo=UTC)  # BDT: July 12, 00:01

        db = self.Session()
        db.add(RiskRuntimeState(id=1, trades_day="2026-07-12", day_start_equity=1000.0))
        db.add(make_test_trade(
            journal_id="trade-1",
            symbol="BTCUSDT",
            status="closed",
            closed_at=t1.isoformat(),
            realized_pnl=-10.0,
        ))
        db.add(make_test_trade(
            journal_id="trade-2",
            symbol="ETHUSDT",
            status="closed",
            closed_at=t2.isoformat(),
            realized_pnl=-20.0,
        ))
        db.commit()
        db.close()

        state = risk.restore_risk_state(now=t2, account_equity=1000.0)
        # Should only include trade-2 (-20.0), excluding trade-1 (-10.0)
        self.assertEqual(state["realized_pnl_today"], -20.0)

    def test_5_duplicate_trade_execution_records_counted_once(self) -> None:
        """5. Duplicate trade/execution records are counted once."""
        db = self.Session()
        now = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
        db.add(RiskRuntimeState(id=1, trades_day="2026-07-12", day_start_equity=1000.0))
        # Two rows representing duplicate records of the same order_id
        db.add(make_test_trade(
            journal_id="trade-1",
            symbol="BTCUSDT",
            status="closed",
            closed_at="2026-07-12T15:00:00+06:00",
            realized_pnl=-10.0,
            order_id="order-duplicate",
        ))
        db.add(make_test_trade(
            journal_id="trade-1-dup",
            symbol="BTCUSDT",
            status="closed",
            closed_at="2026-07-12T15:10:00+06:00",
            realized_pnl=-10.0,
            order_id="order-duplicate",
        ))
        db.commit()
        db.close()

        state = risk.restore_risk_state(now=now, account_equity=1000.0)
        # Only counted once
        self.assertEqual(state["realized_pnl_today"], -10.0)
        self.assertEqual(state["audit_evidence"]["excluded_reasons"].get("duplicated"), 1)

    def test_6_open_and_pending_rows_are_excluded(self) -> None:
        """6. Open and pending rows are excluded."""
        db = self.Session()
        now = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
        db.add(RiskRuntimeState(id=1, trades_day="2026-07-12", day_start_equity=1000.0))
        # Open row
        db.add(make_test_trade(
            journal_id="trade-1",
            symbol="BTCUSDT",
            status="active",
            realized_pnl=-10.0,
        ))
        # Close pending sync / unresolved row
        db.add(make_test_trade(
            journal_id="trade-2",
            symbol="ETHUSDT",
            status="close_pending_sync",
            realized_pnl=-20.0,
        ))
        db.commit()
        db.close()

        state = risk.restore_risk_state(now=now, account_equity=1000.0)
        self.assertEqual(state["realized_pnl_today"], 0.0)
        self.assertEqual(state["audit_evidence"]["excluded_reasons"].get("open"), 1)
        self.assertEqual(state["audit_evidence"]["excluded_reasons"].get("pending"), 1)

    def test_7_missing_realized_pnl_not_treated_as_zero(self) -> None:
        """7. Missing realized PnL is not treated as zero."""
        db = self.Session()
        now = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
        db.add(RiskRuntimeState(id=1, trades_day="2026-07-12", day_start_equity=1000.0))
        db.add(make_test_trade(
            journal_id="trade-1",
            symbol="BTCUSDT",
            status="closed",
            closed_at="2026-07-12T15:00:00+06:00",
            realized_pnl=None,  # Missing PnL
        ))
        db.commit()
        db.close()

        state = risk.restore_risk_state(now=now, account_equity=1000.0)
        self.assertEqual(state["realized_pnl_today"], 0.0)
        self.assertEqual(state["audit_evidence"]["excluded_reasons"].get("missing authoritative realized PnL"), 1)

    def test_8_estimated_close_pnl_excluded(self) -> None:
        """8. Estimated close PnL is excluded from authoritative enforcement."""
        db = self.Session()
        now = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
        db.add(RiskRuntimeState(id=1, trades_day="2026-07-12", day_start_equity=1000.0))
        db.add(make_test_trade(
            journal_id="trade-1",
            symbol="BTCUSDT",
            status="closed",
            closed_at="2026-07-12T15:00:00+06:00",
            realized_pnl=-30.0,
            exchange_metadata='{"close_pnl_is_estimate": true}',
        ))
        db.commit()
        db.close()

        state = risk.restore_risk_state(now=now, account_equity=1000.0)
        # Excluded completely
        self.assertEqual(state["realized_pnl_today"], 0.0)
        self.assertEqual(state["audit_evidence"]["excluded_reasons"].get("explicitly marked as estimated"), 1)

    def test_9_previous_day_tripped_state_resets_safely(self) -> None:
        """9. Previous-day tripped state resets safely on a new operational day."""
        db = self.Session()
        # Yesterday July 11
        previous_day = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
        new_day = datetime(2026, 7, 11, 19, 0, tzinfo=UTC) # Converts to July 12 BDT

        db.add(RiskRuntimeState(
            id=1,
            trades_day="2026-07-11",
            circuit_breaker_active=True,
            circuit_breaker_reason="Old limit hit",
            day_start_equity=1000.0,
        ))
        db.commit()
        db.close()

        state = risk.restore_risk_state(now=new_day, account_equity=1000.0)
        # Tripped state should reset
        self.assertFalse(state["circuit_breaker_active"])
        self.assertEqual(state["trades_day"], "2026-07-12")

    def test_10_same_day_genuine_tripped_state_survives_process_restart(self) -> None:
        """10. Same-day genuine tripped state survives process restart."""
        db = self.Session()
        now = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
        db.add(RiskRuntimeState(
            id=1,
            trades_day="2026-07-12",
            circuit_breaker_active=True,
            circuit_breaker_reason="Genuine daily net realized loss limit reached",
            day_start_equity=1000.0,
        ))
        db.commit()
        db.close()

        state = risk.restore_risk_state(now=now, account_equity=1000.0)
        # Remains tripped
        self.assertTrue(state["circuit_breaker_active"])
        self.assertEqual(state["circuit_breaker_reason"], "Genuine daily net realized loss limit reached")

    def test_11_data_source_failure_produces_fail_closed_readiness_with_explicit_reason(self) -> None:
        """11. Data-source failure produces fail-closed readiness with an explicit reason."""
        now = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)

        # Test directly with failure
        mock_db_direct = MagicMock()
        mock_db_direct.query.side_effect = Exception("DB Connection Timeout")
        audit = risk.calculate_daily_pnl_from_journal(mock_db_direct, "2026-07-12", 1000.0)
        self.assertFalse(audit["ok"])
        self.assertEqual(audit["error"], "DAILY_LOSS_AUTHORITY_UNAVAILABLE")

        # Now mock query specifically so RiskRuntimeState query succeeds but TradeJournal query fails
        mock_db = MagicMock()
        def mock_query(model):
            if model == RiskRuntimeState:
                m = MagicMock()
                m.filter.return_value.first.return_value = RiskRuntimeState(id=1, trades_day="2026-07-12", day_start_equity=1000.0)
                return m
            elif model == TradeJournal:
                raise Exception("DB Connection Timeout")
            return MagicMock()
        mock_db.query.side_effect = mock_query

        # Refresh state should capture failure and fail-closed
        with patch("app.risk.SessionLocal", return_value=mock_db):
            state = risk.refresh_risk_state(account_equity=1000.0, now=now)
        self.assertTrue(state["circuit_breaker_active"])
        self.assertEqual(state["circuit_breaker_reason"], "DAILY_LOSS_AUTHORITY_UNAVAILABLE")

    def test_12_bot_not_stopped_when_loss_threshold_not_breached(self) -> None:
        """12. Bot is not stopped when the authoritative current-day loss threshold has not actually been breached."""
        db = self.Session()
        now = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
        db.add(RiskRuntimeState(id=1, trades_day="2026-07-12", day_start_equity=1000.0))
        db.add(make_test_trade(
            journal_id="trade-1",
            symbol="BTCUSDT",
            status="closed",
            closed_at="2026-07-12T15:00:00+06:00",
            realized_pnl=-40.0, # Loss is 4%, below 5% (50.0 USDT) limit
        ))
        db.commit()
        db.close()

        state = risk.restore_risk_state(now=now, account_equity=1000.0)
        self.assertFalse(state["circuit_breaker_active"])
        self.assertEqual(state["realized_pnl_today"], -40.0)


if __name__ == "__main__":
    unittest.main()

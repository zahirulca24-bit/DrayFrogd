from __future__ import annotations

import unittest
from unittest.mock import patch

import app.execution as execution
from app.batch1_execution_safety import (
    enrich_readiness_with_ws,
    get_daily_loss_authority,
    normalize_execution_block,
)
from app.bybit_websocket import BybitWebSocketService


class FakeLedgerClient:
    mode = "demo"

    @staticmethod
    def safe_fetch_transaction_log(**kwargs):  # noqa: ANN003
        return (
            True,
            [
                {
                    "transactionTime": "1784358000000",
                    "type": "TRADE",
                    "symbol": "BTCUSDT",
                    "change": "-12.5",
                    "fee": "-2.5",
                    "cashBalance": "987.5",
                },
                {
                    "transactionTime": "1784358060000",
                    "type": "TRADE",
                    "symbol": "ETHUSDT",
                    "change": "4.0",
                    "fee": "-1.0",
                    "cashBalance": "991.5",
                },
            ],
            None,
        )


class FakeWalletClient:
    @staticmethod
    def safe_fetch_wallet_balance():
        return True, {"totalEquity": "1000"}, None


class FakeSocket:
    auth = True

    @staticmethod
    def is_connected() -> bool:
        return True


class Batch1ExecutionSafetyTests(unittest.TestCase):
    def test_expected_active_symbol_rejection_is_normalized_to_bounded_block(self) -> None:
        result = normalize_execution_block(
            {"ok": False, "error": "Symbol already has an active trade"}
        )
        self.assertEqual(result["error"], "SYMBOL_ALREADY_ACTIVE")
        self.assertTrue(result["execution_blocked"])
        self.assertEqual(result["detail"], "Symbol already has an active trade")

    def test_private_ws_degradation_is_explicit_rest_fallback_not_full_ready(self) -> None:
        readiness = {
            "ready_for_execution": True,
            "checks": {"admin_auth_configured": True},
        }
        enriched = enrich_readiness_with_ws(
            readiness,
            {
                "private": {
                    "connected": False,
                    "authenticated": False,
                    "state": "reconnecting",
                    "reconnect_count": 3,
                },
                "public": {"connected": True, "state": "connected"},
            },
        )
        self.assertEqual(enriched["execution_readiness_state"], "DEGRADED_REST_FALLBACK")
        self.assertEqual(
            enriched["execution_identity_policy"],
            "rest_execution_list_authoritative_fallback",
        )
        self.assertTrue(enriched["ready_for_execution"])
        self.assertEqual(enriched["websocket"]["private_reconnect_count"], 3)

    def test_private_ws_authenticated_reports_ready(self) -> None:
        enriched = enrich_readiness_with_ws(
            {"ready_for_execution": True, "checks": {"admin_auth_configured": True}},
            {
                "private": {"connected": True, "authenticated": True, "state": "connected"},
                "public": {"connected": True, "state": "connected"},
            },
        )
        self.assertEqual(enriched["execution_readiness_state"], "READY")
        self.assertEqual(
            enriched["execution_identity_policy"],
            "private_ws_plus_rest_reconciliation",
        )

    def test_rest_failure_reports_blocked_even_if_ws_status_exists(self) -> None:
        enriched = enrich_readiness_with_ws(
            {"ready_for_execution": False, "checks": {"admin_auth_configured": True}},
            {
                "private": {"connected": True, "authenticated": True},
                "public": {"connected": True},
            },
        )
        self.assertEqual(enriched["execution_readiness_state"], "BLOCKED")
        self.assertFalse(enriched["ready_for_execution"])

    def test_bybit_transaction_log_is_daily_loss_authority(self) -> None:
        from tempfile import NamedTemporaryFile
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        from app.models import RiskRuntimeState, TradeJournal
        from datetime import UTC, datetime
        from zoneinfo import ZoneInfo
        import app.batch1_execution_safety as safety

        BDT_tz = ZoneInfo("Asia/Dhaka")

        with NamedTemporaryFile(suffix=".db") as db_file:
            engine = create_engine(
                f"sqlite:///{db_file.name}",
                connect_args={"check_same_thread": False},
            )
            Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            Base.metadata.create_all(bind=engine)

            db = Session()
            db.add(RiskRuntimeState(id=1, trades_day=datetime.now(BDT_tz).date().isoformat(), day_start_equity=1000.0))
            db.add(TradeJournal(
                journal_id="trade-1",
                symbol="BTCUSDT",
                direction="long",
                execution_mode="demo",
                entry_price=100.0,
                stop_loss=98.0,
                take_profit=103.0,
                status="closed",
                closed_at=datetime.now(UTC).isoformat(),
                realized_pnl=-8.5,
            ))
            db.commit()
            db.close()

            with patch("app.batch1_execution_safety.SessionLocal", Session):
                authority = get_daily_loss_authority(client=FakeLedgerClient(), force=True)

        self.assertTrue(authority["ok"])
        self.assertEqual(authority["source"], "trade_journal")
        self.assertAlmostEqual(authority["trade_net"], -8.5)
        self.assertAlmostEqual(authority["account_net"], -8.5)
        self.assertEqual(authority["trade_count"], 1)

    def test_public_order_boundary_fails_closed_when_daily_authority_is_unavailable(self) -> None:
        with patch(
            "app.batch1_execution_safety.get_daily_loss_authority",
            return_value={
                "ok": False,
                "source": "bybit_account_transaction_log",
                "error": "ledger unavailable",
            },
        ):
            result = execution._execute_signal_authoritatively(object(), {"symbol": "BTCUSDT"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "DAILY_LOSS_AUTHORITY_UNAVAILABLE")
        self.assertEqual(result["detail"], "ledger unavailable")

    def test_public_order_boundary_blocks_before_order_when_daily_breaker_is_active(self) -> None:
        with (
            patch(
                "app.batch1_execution_safety.get_daily_loss_authority",
                return_value={
                    "ok": True,
                    "source": "bybit_account_transaction_log",
                    "trade_net": -55.0,
                },
            ),
            patch(
                "app.risk.refresh_risk_state",
                return_value={
                    "circuit_breaker_active": True,
                    "circuit_breaker_reason": "Authoritative Bybit daily trade net loss limit reached",
                },
            ),
        ):
            result = execution._execute_signal_authoritatively(FakeWalletClient(), {"symbol": "BTCUSDT"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "DAILY_LOSS_CIRCUIT_BREAKER")
        self.assertIn("Authoritative Bybit", result["detail"])

    def test_private_execution_callback_routes_records_to_persistence(self) -> None:
        service = BybitWebSocketService()
        service._private_ws = FakeSocket()
        record = {
            "symbol": "BTCUSDT",
            "orderId": "order-1",
            "orderLinkId": "link-1",
            "execId": "exec-1",
            "execQty": "1",
            "execPrice": "100",
        }
        with patch("app.batch1_execution_safety.persist_private_execution_records") as persist:
            service._private_callback({"topic": "execution", "data": [record]})
        persist.assert_called_once_with([record])


if __name__ == "__main__":
    unittest.main()

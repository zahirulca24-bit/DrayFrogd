from __future__ import annotations

import unittest
from unittest.mock import patch

from app.authoritative_state import get_snapshot, reset_snapshot
from app.runtime_guard import get_watchdog_execution_block, reset_runtime_guard
from app.runtime_watchdog import run_watchdog_cycle


CONFIG = {
    "enabled": True,
    "interval_seconds": 30,
    "action_mode": "safe_stop",
    "mismatch_tolerance_cycles": 1,
    "exposure_tolerance_ratio": 0.01,
    "pnl_tolerance": 0.10,
    "status": "UNINITIALIZED",
    "execution_blocked": False,
    "reasons": [],
    "consecutive_mismatch_cycles": 0,
    "last_checked_at": None,
    "last_snapshot_version": 0,
}


class FakeClient:
    def __init__(self, *, positions=None, wallet_ok=True, positions_ok=True):
        self.positions = list(positions or [])
        self.wallet_ok = wallet_ok
        self.positions_ok = positions_ok

    def safe_fetch_wallet_balance(self):
        return self.wallet_ok, {"totalEquity": "1000", "totalAvailableBalance": "900"} if self.wallet_ok else None, None if self.wallet_ok else "wallet down"

    def safe_fetch_positions(self):
        return self.positions_ok, list(self.positions) if self.positions_ok else [], None if self.positions_ok else "positions down"

    def safe_fetch_open_orders(self):
        return True, [], None


class RuntimeWatchdogTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_snapshot()
        reset_runtime_guard()

    def _run(self, client, app_trades):
        def persist(config, *, status, execution_blocked, reasons, snapshot, consecutive_mismatch_cycles=None):
            return {
                **config,
                "status": status,
                "execution_blocked": execution_blocked,
                "reasons": reasons,
                "snapshot": snapshot,
                "consecutive_mismatch_cycles": consecutive_mismatch_cycles or 0,
            }

        with (
            patch("app.runtime_watchdog.ensure_watchdog_state", return_value=dict(CONFIG)),
            patch("app.runtime_watchdog.get_operator_active_trades", return_value=app_trades),
            patch("app.runtime_watchdog.get_account_ledger_audit", return_value={"ok": True, "summary": {"net_change": 2.5, "trade_change": 3.0, "fees": -0.5, "funding": 0.0}, "error": None}),
            patch("app.runtime_watchdog._persist_result", side_effect=persist),
            patch("app.runtime_watchdog._log_state_transition"),
        ):
            return run_watchdog_cycle(client, reconciliation_result={"ok": True})

    def test_healthy_snapshot_uses_exchange_and_app_truth(self) -> None:
        position = {"symbol": "BTCUSDT", "size": "2", "markPrice": "100", "avgPrice": "99", "stopLoss": "95", "takeProfit": "110"}
        trade = {"symbol": "BTCUSDT", "quantity": 2, "mark_price": 100, "entry": 99}
        result = self._run(FakeClient(positions=[position]), [trade])

        self.assertEqual(result["status"], "HEALTHY")
        self.assertFalse(result["execution_blocked"])
        snapshot = get_snapshot()
        self.assertEqual(snapshot["exchange_position_count"], 1)
        self.assertEqual(snapshot["app_position_count"], 1)
        self.assertEqual(snapshot["exchange_exposure"], 200.0)
        self.assertEqual(snapshot["account_net"], 2.5)

    def test_position_mismatch_safe_stops_new_execution(self) -> None:
        position = {"symbol": "BTCUSDT", "size": "1", "markPrice": "100", "stopLoss": "95", "takeProfit": "110"}
        result = self._run(FakeClient(positions=[position]), [])

        self.assertEqual(result["status"], "EXECUTION_BLOCKED")
        self.assertTrue(result["execution_blocked"])
        codes = {item["code"] for item in result["reasons"]}
        self.assertIn("POSITION_SET_MISMATCH", codes)
        blocked, reason = get_watchdog_execution_block()
        self.assertTrue(blocked)
        self.assertIn("POSITION_SET_MISMATCH", reason)

    def test_missing_protection_is_critical(self) -> None:
        position = {"symbol": "ETHUSDT", "size": "1", "markPrice": "50", "stopLoss": "0", "takeProfit": "60"}
        trade = {"symbol": "ETHUSDT", "quantity": 1, "mark_price": 50, "entry": 49}
        result = self._run(FakeClient(positions=[position]), [trade])
        codes = {item["code"] for item in result["reasons"]}
        self.assertIn("MISSING_NATIVE_PROTECTION", codes)
        self.assertTrue(result["execution_blocked"])

    def test_exchange_fetch_failure_fails_closed(self) -> None:
        result = self._run(FakeClient(positions_ok=False), [])
        self.assertTrue(result["execution_blocked"])
        self.assertEqual(result["status"], "EXECUTION_BLOCKED")


if __name__ == "__main__":
    unittest.main()

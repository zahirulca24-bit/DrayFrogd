from __future__ import annotations

import json
import uuid
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch, MagicMock

import app.scanner as scanner
from app.database import Base, SessionLocal, engine
from app.models import ScannerSnapshot, BotRuntimeConfig
from app.scanner import (
    execute_backend_scan,
    get_scanner_runtime_state,
    get_latest_successful_snapshot,
    get_latest_attempted_snapshot,
    is_scanner_running,
    get_active_signals,
    get_latest_signals,
)
from app.bot_controls import ensure_runtime_config, start_bot, stop_bot


class FakeClient:
    def __init__(self) -> None:
        pass

    def safe_fetch_market_tickers(self):
        return True, [], None


class ScannerPersistenceAndRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            db.query(ScannerSnapshot).delete()
            db.query(BotRuntimeConfig).delete()
            db.commit()
        finally:
            db.close()

        ensure_runtime_config()

        scanner._latest_signals.clear()
        scanner._latest_scan_results.clear()
        scanner._latest_ranked_markets.clear()
        scanner._scanner_running = False
        scanner._last_scan_failed = False
        scanner._last_scan_failure_reason = None

    def test_automatic_scan_without_frontend(self) -> None:
        # 1. Automatic scanner runs without any browser/frontend connection.
        client = FakeClient()
        dummy_scan_result = {
            "ok": True,
            "symbols_scanned": 15,
            "signals": [{"symbol": "BTCUSDT", "status": "active", "direction": "long"}],
            "results": [{"symbol": "BTCUSDT", "strategy_name": "ema_pullback", "status": "active"}]
        }

        with patch("app.scanner.run_scan", return_value=dummy_scan_result):
            res = execute_backend_scan(client, "automatic")

        self.assertTrue(res["ok"])
        snap = get_latest_successful_snapshot()
        self.assertIsNotNone(snap)
        self.assertEqual(snap.trigger_source, "automatic")
        self.assertEqual(snap.symbols_scanned, 15)

    def test_survives_navigation_refresh_and_backend_restart(self) -> None:
        # 2. Latest successful scan survives page navigation.
        # 3. Latest successful scan survives frontend refresh.
        # 4. Latest successful scan survives backend restart.
        client = FakeClient()
        dummy_scan_result = {
            "ok": True,
            "symbols_scanned": 15,
            "signals": [{"symbol": "BTCUSDT", "status": "active", "direction": "long"}],
            "results": [{"symbol": "BTCUSDT", "strategy_name": "ema_pullback", "status": "active"}],
            "ranked_markets": [{"symbol": "BTCUSDT", "market_rank": 1}]
        }

        with patch("app.scanner.run_scan", return_value=dummy_scan_result):
            execute_backend_scan(client, "automatic")

        scanner._latest_signals.clear()
        scanner._latest_scan_results.clear()
        scanner._latest_ranked_markets.clear()

        recovered_latest = get_latest_signals()
        recovered_active = get_active_signals()

        self.assertEqual(len(recovered_latest), 1)
        self.assertEqual(len(recovered_active), 1)
        self.assertEqual(recovered_latest[0]["symbol"], "BTCUSDT")

    def test_manual_and_automatic_same_pipeline(self) -> None:
        # 5. Manual and automatic scans use the same pipeline.
        client = FakeClient()
        dummy_scan_result = {"ok": True, "symbols_scanned": 12, "signals": []}

        with patch("app.scanner.run_scan", return_value=dummy_scan_result) as run_mock:
            execute_backend_scan(client, "automatic")
            execute_backend_scan(client, "manual")

        self.assertEqual(run_mock.call_count, 2)

    def test_overlapping_scans_prevented_and_manual_conflict(self) -> None:
        # 6. Overlapping scans are prevented.
        # 7. Manual scan during an active automatic scan returns a clear "already running" response.
        client = FakeClient()

        scanner._scanner_running = True
        res = execute_backend_scan(client, "manual")

        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "ALREADY_RUNNING")
        self.assertIn("already running", res["error"])

    def test_failed_scan_does_not_erase_successful_snapshot(self) -> None:
        # 8. Failed scan does not erase the latest successful snapshot.
        client = FakeClient()
        success_result = {"ok": True, "symbols_scanned": 10, "signals": []}
        failed_result = {"ok": False, "error": "Bybit API offline"}

        with patch("app.scanner.run_scan", return_value=success_result):
            execute_backend_scan(client, "automatic")

        success_snap = get_latest_successful_snapshot()
        self.assertIsNotNone(success_snap)
        self.assertEqual(success_snap.symbols_scanned, 10)

        with patch("app.scanner.run_scan", return_value=failed_result):
            execute_backend_scan(client, "automatic")

        success_snap_after = get_latest_successful_snapshot()
        self.assertEqual(success_snap_after.scan_id, success_snap.scan_id)
        self.assertEqual(success_snap_after.symbols_scanned, 10)

        attempted = get_latest_attempted_snapshot()
        self.assertEqual(attempted.status, "failed")
        self.assertEqual(attempted.failure_reason, "Bybit API offline")

    def test_scanner_state_reports_correct_states_and_next_time(self) -> None:
        # 9. Scanner state endpoint reports correct running/idle/stopped state.
        # 10. Next automatic scan time is calculated correctly.

        with patch("app.runtime_guard.get_watchdog_execution_block", return_value=(False, None)):
            stop_bot()
            state = get_scanner_runtime_state()
            self.assertEqual(state["status"], "stopped")

            start_bot()
            state = get_scanner_runtime_state()
            self.assertEqual(state["status"], "idle")

            scanner._scanner_running = True
            state = get_scanner_runtime_state()
            self.assertEqual(state["status"], "running")
            scanner._scanner_running = False

            client = FakeClient()
            success_result = {"ok": True, "symbols_scanned": 5, "signals": []}
            with patch("app.scanner.run_scan", return_value=success_result):
                execute_backend_scan(client, "automatic")

            state = get_scanner_runtime_state()
            self.assertIsNotNone(state["next_expected_automatic_scan_time"])
            self.assertIsNotNone(state["last_successful_completion_time"])

    def test_browser_local_state_not_authoritative(self) -> None:
        # 11. Browser-local state is not the authoritative source.
        db = SessionLocal()
        try:
            count = db.query(ScannerSnapshot).count()
            self.assertEqual(count, 0)

            client = FakeClient()
            with patch("app.scanner.run_scan", return_value={"ok": True, "symbols_scanned": 8, "signals": []}):
                execute_backend_scan(client, "manual")

            count_after = db.query(ScannerSnapshot).count()
            self.assertEqual(count_after, 1)
        finally:
            db.close()

    def test_no_silent_execution_enablement(self) -> None:
        # 12. Scanner does not silently enable execution or weaken safety gates.
        bot_state_before = scanner.get_scanner_runtime_state()
        client = FakeClient()
        with patch("app.scanner.run_scan", return_value={"ok": True, "symbols_scanned": 8, "signals": []}):
            execute_backend_scan(client, "automatic")

        config = SessionLocal().query(BotRuntimeConfig).first()
        self.assertIsNotNone(config)
        self.assertEqual(config.max_open_trades, 5)
        self.assertEqual(config.leverage_cap, 20.0)

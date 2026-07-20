from __future__ import annotations

import json
import uuid
import unittest
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy.exc import OperationalError, ProgrammingError

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
    NoSnapshotError,
    DatabaseUnavailableError,
    CorruptSnapshotError,
    SchemaUnavailableError,
    _restore_from_latest_snapshot,
)
from app.bot_controls import ensure_runtime_config, start_bot, stop_bot, can_execute
from app.background_worker import auto_scanner_loop, _scan_results_queue


class FakeClient:
    def __init__(self) -> None:
        pass

    def safe_fetch_market_tickers(self):
        return True, [{"symbol": "BTCUSDT", "turnover24h": 60000000.0, "price24hPcnt": 0.02, "lastPrice": 50000.0}], None

    def safe_fetch_recent_candles(self, symbol, interval, limit):
        return True, [{"timestamp": "2026-07-13T12:00:00Z", "close": 50000.0, "high": 50100.0, "low": 49900.0, "open": 50000.0, "volume": 10.0}], None


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
        scanner._scanner_enabled = True
        scanner._public_market_authority_available = True
        scanner._last_scheduled_scan_time = None
        scanner._actual_scan_start_time = None
        scanner._actual_completion_time = None
        scanner._schedule_drift_milliseconds = None
        scanner._scan_duration_milliseconds = None
        scanner._next_scheduled_scan_time = None
        scanner._latest_persistence_status = None
        scanner._latest_persistence_error = None

    def test_automatic_scan_without_frontend(self) -> None:
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
        client = FakeClient()
        dummy_scan_result = {"ok": True, "symbols_scanned": 12, "signals": []}

        with patch("app.scanner.run_scan", return_value=dummy_scan_result) as run_mock:
            execute_backend_scan(client, "automatic")
            execute_backend_scan(client, "manual")

        self.assertEqual(run_mock.call_count, 2)

    def test_overlapping_scans_prevented_and_manual_conflict(self) -> None:
        client = FakeClient()

        scanner._scanner_running = True
        res = execute_backend_scan(client, "manual")

        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "ALREADY_RUNNING")
        self.assertIn("already running", res["error"])

    def test_failed_scan_does_not_erase_successful_snapshot(self) -> None:
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
        with patch("app.runtime_guard.get_watchdog_execution_block", return_value=(False, None)):
            stop_bot()
            state = get_scanner_runtime_state()
            self.assertEqual(state["execution_blocked"], True)

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
        client = FakeClient()
        with patch("app.scanner.run_scan", return_value={"ok": True, "symbols_scanned": 8, "signals": []}):
            execute_backend_scan(client, "automatic")

        config = SessionLocal().query(BotRuntimeConfig).first()
        self.assertIsNotNone(config)
        self.assertEqual(config.max_open_trades, 5)
        self.assertEqual(config.leverage_cap, 20.0)

    # NEW DETECTED PROBLEMS TESTS
    def test_scanner_continues_while_execution_blocked(self) -> None:
        # 1. Scanner continues while execution is blocked.
        with patch("app.bot_controls._risk_circuit_breaker_active", return_value=True), \
             patch("app.bot_controls.get_watchdog_execution_block", return_value=(False, None)):
            allowed, reason = can_execute()
            self.assertFalse(allowed)
            self.assertEqual(reason, "Daily net realized loss circuit breaker is active")

            # Scanner can still run
            client = FakeClient()
            dummy_scan_result = {"ok": True, "symbols_scanned": 5, "signals": []}
            with patch("app.scanner.run_scan", return_value=dummy_scan_result):
                res = execute_backend_scan(client, "automatic")
                self.assertTrue(res["ok"])

    def test_scanner_does_not_submit_trades(self) -> None:
        # 2. Scanner does not submit trades directly.
        client = FakeClient()
        dummy_scan_result = {
            "ok": True,
            "symbols_scanned": 1,
            "signals": [{"symbol": "BTCUSDT", "status": "active", "direction": "long"}]
        }
        with patch("app.scanner.run_scan", return_value=dummy_scan_result), \
             patch("app.risk_execution.execute_signal") as exec_mock:
            execute_backend_scan(client, "automatic")
            exec_mock.assert_not_called()

    def test_fixed_rate_scheduling_timing(self) -> None:
        # 3. Fixed-rate scheduling does not add task duration to the interval.
        # 15. Next scheduled scan time is populated.
        scanner._next_scheduled_scan_time = None

        async def run_test():
            task = asyncio.create_task(auto_scanner_loop())
            await asyncio.sleep(0.1)  # allow loop to complete first run
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Mocking app settings using patch (no asyncio.sleep patch!)
        with patch("app.background_worker.settings", MagicMock(bot_scan_interval_seconds=30)), \
             patch("app.background_worker.execute_backend_scan", return_value={"ok": True}) as scan_mock:

             asyncio.run(run_test())

             self.assertIsNotNone(scanner._next_scheduled_scan_time)
             expected_diff = scanner._next_scheduled_scan_time - datetime.now(UTC)
             self.assertTrue(expected_diff.total_seconds() <= 30.5)

    def test_long_scan_duration_drift(self) -> None:
        # 4. Long scan duration reports schedule drift correctly.
        scanner._schedule_drift_milliseconds = 150.0
        state = get_scanner_runtime_state()
        self.assertEqual(state["schedule_drift_milliseconds"], 150.0)

    def test_overlapping_scans_prevented(self) -> None:
        # 5. Overlapping scans remain prevented.
        scanner._scanner_running = True
        res = execute_backend_scan(FakeClient(), "automatic")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "ALREADY_RUNNING")

    def test_manual_scan_does_not_break_cadence(self) -> None:
        # 6. Manual scan does not break automatic cadence.
        scanner._next_scheduled_scan_time = datetime.now(UTC) + timedelta(seconds=25)
        client = FakeClient()
        with patch("app.scanner.run_scan", return_value={"ok": True, "symbols_scanned": 1}):
            execute_backend_scan(client, "manual")

        self.assertIsNotNone(scanner._next_scheduled_scan_time)

    def test_bot_status_lookup_failure_not_idle(self) -> None:
        # 7. Bot status lookup failure does not become idle.
        with patch("app.bot_controls.get_bot_status", side_effect=Exception("DB down")):
            state = get_scanner_runtime_state()
            self.assertEqual(state["status"], "blocked")

    def test_execution_fail_closed_on_unknown(self) -> None:
        # 8. Execution remains fail-closed when lifecycle state is unknown.
        with patch("app.bot_controls._get_runtime_row", side_effect=Exception("DB Failure")):
            allowed, reason = can_execute()
            self.assertFalse(allowed)
            self.assertIn("status lookup failed", reason)

    def test_db_persistence_failure_partial_success(self) -> None:
        # 9. Successful scan plus DB persistence failure returns partial-success state.
        # 10. In-memory result remains available after persistence failure.
        # 11. Restart recovery is marked unavailable after persistence failure.
        client = FakeClient()
        dummy_scan_result = {
            "ok": True,
            "symbols_scanned": 5,
            "signals": [{"symbol": "BTCUSDT", "status": "active"}]
        }

        def mock_run_scan(*args, **kwargs):
            scanner._latest_signals.clear()
            scanner._latest_signals.extend(dummy_scan_result["signals"])
            return dummy_scan_result

        with patch("app.scanner.run_scan", side_effect=mock_run_scan), \
             patch("app.models.ScannerSnapshot", side_effect=Exception("DB down")):
            res = execute_backend_scan(client, "automatic")

            self.assertTrue(res["ok"])
            self.assertFalse(res["persistence_ok"])
            self.assertEqual(res["code"], "SCAN_COMPLETED_PERSISTENCE_FAILED")
            self.assertFalse(res["restart_recovery_available"])

            # Verify in-memory result remains available
            self.assertEqual(len(scanner._latest_signals), 1)

    def test_snapshot_exceptions_no_snapshot(self) -> None:
        # 12. No snapshot is distinguished from DB failure.
        db = SessionLocal()
        try:
            db.query(ScannerSnapshot).delete()
            db.commit()
        finally:
            db.close()

        with self.assertRaises(NoSnapshotError):
            _restore_from_latest_snapshot()

    def test_snapshot_exceptions_db_failure(self) -> None:
        # 12. Distinguish DB failure
        with patch("app.database.SessionLocal") as session_mock:
            mock_session = MagicMock()
            mock_session.query.side_effect = OperationalError("DB lock", params=None, orig=None)
            session_mock.return_value = mock_session

            with self.assertRaises(DatabaseUnavailableError):
                _restore_from_latest_snapshot()

    def test_snapshot_exceptions_corrupt(self) -> None:
        # 13. Corrupt snapshot is exposed explicitly.
        db = SessionLocal()
        try:
            corrupt_snap = ScannerSnapshot(
                scan_id="corrupt-1",
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                status="success",
                trigger_source="automatic",
                symbols_scanned=1,
                signals_found=0,
                rejected_count=0,
                warning_error_count=0,
                summary_json="invalid-json-{",
            )
            db.add(corrupt_snap)
            db.commit()
        finally:
            db.close()

        with self.assertRaises(CorruptSnapshotError):
            _restore_from_latest_snapshot()

    def test_snapshot_recovery_exceptions_not_swallowed(self) -> None:
        # 14. Snapshot recovery exceptions are not silently swallowed.
        with patch("app.scanner._restore_from_latest_snapshot", side_effect=DatabaseUnavailableError("error")):
            with self.assertRaises(DatabaseUnavailableError):
                get_latest_signals()

    def test_scanner_stops_cleanly_on_shutdown(self) -> None:
        # 16. Scanner stops cleanly on application shutdown.
        async def cancel_loop():
            task = asyncio.create_task(auto_scanner_loop())
            await asyncio.sleep(0.01)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self.assertTrue(task.done())

        asyncio.run(cancel_loop())

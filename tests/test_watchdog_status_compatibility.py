"""Regression coverage for the Control Center watchdog response contract."""

import unittest
from unittest.mock import patch

from app.main import app


class WatchdogStatusCompatibilityTests(unittest.TestCase):
    def test_watchdog_status_preserves_control_panel_contract(self) -> None:
        expected_runtime = {
            "enabled": True,
            "status": "HEALTHY",
            "execution_blocked": False,
            "reasons": [],
        }
        expected_operations = {
            "generated_at": "2026-07-17T00:00:00+00:00",
            "mode": "demo",
            "admin_auth_configured": True,
            "modules": [],
            "incidents": [],
            "summary": {
                "overall_status": "HEALTHY",
                "open_incidents": 0,
                "total_incidents": 0,
                "affected_modules": [],
            },
        }

        route = next(
            route
            for route in app.routes
            if getattr(route, "path", None) == "/watchdog/status"
        )

        with (
            patch(
                "app.watchdog.get_watchdog_snapshot",
                side_effect=lambda worker_running: dict(expected_operations),
            ),
            patch(
                "app.runtime_watchdog.ensure_watchdog_state",
                return_value=dict(expected_runtime),
            ),
            patch("app.runtime_watchdog.get_snapshot", return_value={"version": 1}),
        ):
            result = route.endpoint(_={"sub": "test"})

        self.assertEqual(result["modules"], [])
        self.assertEqual(result["incidents"], [])
        self.assertEqual(result["summary"]["overall_status"], "HEALTHY")
        self.assertEqual(result["runtime"]["status"], "HEALTHY")
        self.assertEqual(result["runtime"]["snapshot"], {"version": 1})


if __name__ == "__main__":
    unittest.main()

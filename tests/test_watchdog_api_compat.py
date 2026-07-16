from __future__ import annotations

import unittest
from pathlib import Path


class WatchdogApiCompatibilityTests(unittest.TestCase):
    def test_watchdog_routes_preserve_control_page_contract(self) -> None:
        source = Path("app/main.py").read_text(encoding="utf-8")
        self.assertIn('@app.get("/watchdog/status")', source)
        self.assertIn('return get_watchdog_snapshot(worker_running=worker_running)', source)
        self.assertIn('@app.get("/watchdog/runtime-status")', source)
        self.assertIn('return get_watchdog_runtime_status()', source)
        self.assertIn('@app.get("/watchdog/operations")', source)

    def test_frontend_control_contract_still_requests_operational_status(self) -> None:
        source = Path("frontend/src/api.ts").read_text(encoding="utf-8")
        self.assertIn(
            'getWatchdogStatus: (token: string) => request<WatchdogSnapshot>("/watchdog/status"',
            source,
        )


if __name__ == "__main__":
    unittest.main()

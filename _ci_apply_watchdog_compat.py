from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected anchor not found in {path}: {old[:160]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/main.py",
    '@app.get("/watchdog/status")\ndef watchdog_status(_: dict = Depends(require_authenticated)) -> dict:\n    return get_watchdog_runtime_status()\n\n\n@app.get("/watchdog/operations")\n',
    '@app.get("/watchdog/status")\ndef watchdog_status(_: dict = Depends(require_authenticated)) -> dict:\n    global _background_task\n    worker_running = _background_task is not None and not _background_task.done()\n    return get_watchdog_snapshot(worker_running=worker_running)\n\n\n@app.get("/watchdog/runtime-status")\ndef watchdog_runtime_status(_: dict = Depends(require_authenticated)) -> dict:\n    return get_watchdog_runtime_status()\n\n\n@app.get("/watchdog/operations")\n',
)

Path("tests/test_watchdog_api_compat.py").write_text(
    '''from __future__ import annotations\n\nimport unittest\nfrom pathlib import Path\n\n\nclass WatchdogApiCompatibilityTests(unittest.TestCase):\n    def test_watchdog_routes_preserve_control_page_contract(self) -> None:\n        source = Path("app/main.py").read_text(encoding="utf-8")\n        self.assertIn('@app.get("/watchdog/status")', source)\n        self.assertIn('return get_watchdog_snapshot(worker_running=worker_running)', source)\n        self.assertIn('@app.get("/watchdog/runtime-status")', source)\n        self.assertIn('return get_watchdog_runtime_status()', source)\n        self.assertIn('@app.get("/watchdog/operations")', source)\n\n    def test_frontend_control_contract_still_requests_operational_status(self) -> None:\n        source = Path("frontend/src/api.ts").read_text(encoding="utf-8")\n        self.assertIn(\n            'getWatchdogStatus: (token: string) => request<WatchdogSnapshot>("/watchdog/status"',\n            source,\n        )\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    encoding="utf-8",
)

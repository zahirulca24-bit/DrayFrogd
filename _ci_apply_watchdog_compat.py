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
    '''from __future__ import annotations\n\nfrom app import main\n\n\ndef test_watchdog_routes_preserve_control_page_contract() -> None:\n    paths = {route.path for route in main.app.routes}\n    assert "/watchdog/status" in paths\n    assert "/watchdog/runtime-status" in paths\n    assert "/watchdog/operations" in paths\n\n\ndef test_watchdog_status_returns_operational_snapshot(monkeypatch) -> None:\n    expected = {\n        "generated_at": "2026-07-17T04:00:00+00:00",\n        "mode": "demo",\n        "admin_auth_configured": True,\n        "modules": [],\n        "incidents": [],\n        "summary": {\n            "overall_status": "HEALTHY",\n            "open_incidents": 0,\n            "total_incidents": 0,\n            "affected_modules": [],\n        },\n    }\n    monkeypatch.setattr(main, "_background_task", None)\n    monkeypatch.setattr(main, "get_watchdog_snapshot", lambda worker_running: expected)\n    assert main.watchdog_status({}) == expected\n\n\ndef test_runtime_status_remains_available(monkeypatch) -> None:\n    expected = {"status": "HEALTHY", "execution_blocked": False}\n    monkeypatch.setattr(main, "get_watchdog_runtime_status", lambda: expected)\n    assert main.watchdog_runtime_status({}) == expected\n''',
    encoding="utf-8",
)

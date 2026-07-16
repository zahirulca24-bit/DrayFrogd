"""Regression coverage for the Control Center watchdog response contract."""

from app.main import app


def test_watchdog_status_preserves_control_panel_contract(monkeypatch):
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

    monkeypatch.setattr("app.watchdog.get_watchdog_snapshot", lambda worker_running: dict(expected_operations))
    monkeypatch.setattr("app.runtime_watchdog.ensure_watchdog_state", lambda: dict(expected_runtime))
    monkeypatch.setattr("app.runtime_watchdog.get_snapshot", lambda: {"version": 1})

    route = next(route for route in app.routes if getattr(route, "path", None) == "/watchdog/status")
    result = route.endpoint(_={"sub": "test"})

    assert result["modules"] == []
    assert result["incidents"] == []
    assert result["summary"]["overall_status"] == "HEALTHY"
    assert result["runtime"]["status"] == "HEALTHY"
    assert result["runtime"]["snapshot"] == {"version": 1}

from fastapi.testclient import TestClient

from app.main import app


def test_watchdog_status_preserves_control_panel_contract(monkeypatch):
    expected = {
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
    monkeypatch.setattr("app.main.get_watchdog_snapshot", lambda worker_running: expected)
    monkeypatch.setattr("app.main.require_authenticated", lambda: {"sub": "test"})

    route = next(route for route in app.routes if getattr(route, "path", None) == "/watchdog/status")
    result = route.endpoint(_={"sub": "test"})

    assert result == expected
    assert isinstance(result["modules"], list)
    assert isinstance(result["incidents"], list)
    assert "summary" in result


def test_watchdog_runtime_status_has_dedicated_endpoint(monkeypatch):
    expected = {
        "state": "HEALTHY",
        "execution_blocked": False,
        "reasons": [],
    }
    monkeypatch.setattr("app.main.get_watchdog_runtime_status", lambda: expected)

    route = next(route for route in app.routes if getattr(route, "path", None) == "/watchdog/runtime-status")
    result = route.endpoint(_={"sub": "test"})

    assert result == expected

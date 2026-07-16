from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from typing import Any

_lock = RLock()
_state: dict[str, Any] = {
    "blocked": False,
    "reason": "",
    "status": "UNINITIALIZED",
    "updated_at": None,
}


def set_watchdog_execution_block(blocked: bool, reason: str = "", *, status: str = "HEALTHY") -> dict[str, Any]:
    global _state
    with _lock:
        _state = {
            "blocked": bool(blocked),
            "reason": str(reason or ""),
            "status": str(status or "HEALTHY"),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        return deepcopy(_state)


def get_watchdog_execution_block() -> tuple[bool, str]:
    with _lock:
        return bool(_state["blocked"]), str(_state["reason"])


def get_runtime_guard_state() -> dict[str, Any]:
    with _lock:
        return deepcopy(_state)


def reset_runtime_guard() -> None:
    set_watchdog_execution_block(False, "", status="UNINITIALIZED")

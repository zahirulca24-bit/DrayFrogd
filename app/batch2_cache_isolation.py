from __future__ import annotations

from functools import wraps
from typing import Any

_INSTALLED = False


def install() -> None:
    """Prevent explicit client/account reads from contaminating the shared runtime cache."""

    global _INSTALLED
    if _INSTALLED:
        return

    import app.batch1_execution_safety as safety

    original = safety.get_daily_loss_authority

    @wraps(original)
    def isolated_daily_loss_authority(*, client: Any | None = None, force: bool = False) -> dict[str, Any]:
        if client is None:
            return original(client=None, force=force)

        # Explicit client reads are order-bound/account-bound truth checks. They must
        # never seed a mode/day-only cache that can later be consumed by another
        # client, test account, credential set or restored runtime context.
        result = original(client=client, force=True)
        with safety._CACHE_LOCK:
            safety._AUTHORITY_CACHE.clear()
        return result

    with safety._CACHE_LOCK:
        safety._AUTHORITY_CACHE.clear()
    safety.get_daily_loss_authority = isolated_daily_loss_authority
    _INSTALLED = True

from __future__ import annotations


def install() -> None:
    """Ensure long-lived imports use the final Batch-2 execution gate."""

    import app.background_worker as background_worker
    import app.bot_controls as bot_controls

    background_worker.can_execute = bot_controls.can_execute

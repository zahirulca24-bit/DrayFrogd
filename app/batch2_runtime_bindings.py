from __future__ import annotations


def install() -> None:
    """Ensure long-lived imports use the final execution and control gates."""

    import app.background_worker as background_worker
    import app.bot_controls as bot_controls

    background_worker.can_execute = bot_controls.can_execute
    # Fee-budget rejection is an expected pre-order safety block, not an
    # execution incident. No exchange order has been submitted at this point.
    background_worker.EXPECTED_EXECUTION_BLOCKS.add("FEE_BUDGET_EXCEEDED")

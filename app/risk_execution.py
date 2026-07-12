"""Compatibility import for the authoritative execution service.

New code should import app.execution.execute_signal or
app.execution_service.execute_signal directly. This module intentionally has no
import-time mutation or monkey patching.
"""

from app.execution_service import execute_signal

__all__ = ["execute_signal"]

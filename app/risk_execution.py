"""Compatibility import for the authoritative execution API.

New code should import app.execution.execute_signal directly. This module has no
import-time mutation or monkey patching.
"""

from app.execution import execute_signal

__all__ = ["execute_signal"]

from __future__ import annotations

from math import isfinite
from typing import Any


MAX_SPREAD_BPS = 50.0


def calculate_spread_bps(ticker: dict[str, Any]) -> float | None:
    bid = _positive_float(ticker.get("bid1Price"))
    ask = _positive_float(ticker.get("ask1Price"))
    if bid is None or ask is None or ask < bid:
        return None
    midpoint = (bid + ask) / 2.0
    if midpoint <= 0:
        return None
    return ((ask - bid) / midpoint) * 10_000.0


def validate_spread(ticker: dict[str, Any], max_spread_bps: float = MAX_SPREAD_BPS) -> dict[str, Any]:
    spread = calculate_spread_bps(ticker)
    if spread is None:
        return {
            "allowed": False,
            "reason": "SPREAD_UNAVAILABLE",
            "spread_bps": None,
            "max_spread_bps": float(max_spread_bps),
        }
    if spread > float(max_spread_bps) + 1e-9:
        return {
            "allowed": False,
            "reason": f"Spread {spread:.2f} bps exceeds maximum {float(max_spread_bps):.2f} bps",
            "spread_bps": spread,
            "max_spread_bps": float(max_spread_bps),
        }
    return {
        "allowed": True,
        "reason": "",
        "spread_bps": spread,
        "max_spread_bps": float(max_spread_bps),
    }


def _positive_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) and numeric > 0 else None

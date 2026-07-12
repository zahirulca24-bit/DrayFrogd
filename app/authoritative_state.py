from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from typing import Any

_lock = RLock()
_snapshot: dict[str, Any] = {
    "version": 0,
    "mode": "demo",
    "source": "uninitialized",
    "updated_at": None,
    "positions_synced": False,
    "trades": [],
    "errors": [],
}


def publish_snapshot(
    trades: list[dict[str, Any]],
    *,
    mode: str,
    source: str,
    positions_synced: bool,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    global _snapshot
    with _lock:
        _snapshot = {
            "version": int(_snapshot.get("version") or 0) + 1,
            "mode": str(mode or "demo").lower(),
            "source": source,
            "updated_at": datetime.now(UTC).isoformat(),
            "positions_synced": bool(positions_synced),
            "trades": deepcopy(trades),
            "errors": list(errors or []),
        }
        return deepcopy(_snapshot)


def get_snapshot() -> dict[str, Any]:
    with _lock:
        return deepcopy(_snapshot)


def get_authoritative_trades() -> list[dict[str, Any]]:
    return list(get_snapshot().get("trades") or [])


def patch_ticker(symbol: str, ticker: dict[str, Any]) -> bool:
    normalized = str(symbol or "").upper().strip()
    if not normalized:
        return False

    changed = False
    with _lock:
        trades = _snapshot.get("trades") or []
        for trade in trades:
            if str(trade.get("symbol") or "").upper() != normalized:
                continue
            mark_price = _number(ticker.get("markPrice") or ticker.get("lastPrice"))
            if mark_price is not None:
                trade["mark_price"] = mark_price
                entry = _number(trade.get("entry"))
                quantity = _number(trade.get("remaining_quantity") or trade.get("quantity"))
                direction = str(trade.get("direction") or "").lower()
                if entry is not None and quantity is not None:
                    pnl = (mark_price - entry) * quantity
                    if direction == "short":
                        pnl *= -1
                    trade["unrealized_pnl"] = pnl
                changed = True
        if changed:
            _snapshot["version"] = int(_snapshot.get("version") or 0) + 1
            _snapshot["updated_at"] = datetime.now(UTC).isoformat()
            _snapshot["source"] = "bybit_public_websocket"
    return changed


def reset_snapshot() -> None:
    global _snapshot
    with _lock:
        _snapshot = {
            "version": 0,
            "mode": "demo",
            "source": "uninitialized",
            "updated_at": None,
            "positions_synced": False,
            "trades": [],
            "errors": [],
        }


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

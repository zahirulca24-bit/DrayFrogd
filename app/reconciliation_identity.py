from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any


def _position_identity(position: dict[str, Any], mode: str) -> tuple[str, str, str, int]:
    side = str(position.get("side") or "").lower()
    direction = "long" if side == "buy" else "short" if side == "sell" else ""
    try:
        position_idx = int(position.get("positionIdx") or 0)
    except (TypeError, ValueError):
        position_idx = 0
    return (
        mode,
        str(position.get("symbol") or "").upper().strip(),
        direction,
        position_idx,
    )


def _trade_identity(trade: dict[str, Any], default_mode: str) -> tuple[str, str, str, int]:
    metadata_identity = _metadata_identity(trade)
    if metadata_identity is not None:
        return metadata_identity
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    position_snapshot = metadata.get("position_snapshot") if isinstance(metadata.get("position_snapshot"), dict) else {}
    try:
        position_idx = int(position_snapshot.get("positionIdx") or 0)
    except (TypeError, ValueError):
        position_idx = 0
    return (
        str(trade.get("execution_mode") or default_mode).lower(),
        str(trade.get("symbol") or "").upper().strip(),
        str(trade.get("direction") or "").lower().strip(),
        position_idx,
    )


def _metadata_identity(trade: dict[str, Any]) -> tuple[str, str, str, int] | None:
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    identity = metadata.get("exchange_identity") if isinstance(metadata.get("exchange_identity"), dict) else {}
    if not identity:
        return None
    try:
        position_idx = int(identity.get("position_idx") or 0)
    except (TypeError, ValueError):
        position_idx = 0
    mode = str(identity.get("mode") or trade.get("execution_mode") or "demo").lower()
    symbol = str(identity.get("symbol") or trade.get("symbol") or "").upper()
    direction = str(identity.get("direction") or trade.get("direction") or "").lower()
    return (mode, symbol, direction, position_idx)


def _identity_payload(identity: tuple[str, str, str, int]) -> dict[str, Any]:
    return {
        "mode": identity[0],
        "symbol": identity[1],
        "direction": identity[2],
        "position_idx": identity[3],
        "key": "|".join(map(str, identity)),
    }


def _orders_by_identity(
    open_orders: list[dict[str, Any]],
    mode: str,
) -> dict[tuple[str, str, str, int], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str, int], list[dict[str, Any]]] = {}
    for order in open_orders:
        side = str(order.get("side") or "").lower()
        direction = "long" if side == "buy" else "short" if side == "sell" else ""
        try:
            position_idx = int(order.get("positionIdx") or 0)
        except (TypeError, ValueError):
            position_idx = 0
        identity = (mode, str(order.get("symbol") or "").upper(), direction, position_idx)
        grouped.setdefault(identity, []).append(order)
    return grouped


def _position_snapshot(position: dict[str, Any]) -> dict[str, Any]:
    size = _coerce_float(position.get("size"), 0.0)
    entry = _coerce_float(position.get("avgPrice") or position.get("entryPrice"), 0.0)
    mark_price = _coerce_float(position.get("markPrice"), None)
    leverage = _coerce_float(position.get("leverage"), None)
    position_value = _coerce_float(position.get("positionValue"), None)
    unrealized = _coerce_float(position.get("unrealisedPnl") or position.get("unrealizedPnl"), None)
    position_margin = _coerce_float(
        position.get("positionIM") or position.get("positionBalance") or position.get("positionMargin"),
        None,
    )
    pnl_percent = None
    if unrealized is not None and position_margin and position_margin > 0:
        pnl_percent = unrealized / position_margin * 100.0
    return {
        "size": size,
        "entry": entry,
        "mark_price": mark_price,
        "leverage": leverage,
        "position_value": position_value,
        "position_margin": position_margin,
        "unrealized_pnl": unrealized,
        "pnl_percent": pnl_percent,
        "liquidation_price": _coerce_float(position.get("liqPrice"), None),
        "stop_loss": _coerce_float(position.get("stopLoss"), None),
        "take_profit": _coerce_float(position.get("takeProfit"), None),
        "direction": "long" if str(position.get("side") or "").lower() == "buy" else "short",
        "live_metrics_available": mark_price is not None and unrealized is not None,
    }


def _position_is_open(position: dict[str, Any]) -> bool:
    try:
        size = float(position.get("size", 0))
    except (TypeError, ValueError):
        return False
    side = str(position.get("side") or "").lower()
    return isfinite(size) and size > 0 and side in {"buy", "sell"}


def _coerce_float(value: Any, fallback: Any) -> float | Any:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    return numeric if isfinite(numeric) else fallback


def _ticker_price_map(tickers: list[dict[str, Any]]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for ticker in tickers:
        symbol = str(ticker.get("symbol", "")).upper()
        price = _coerce_float(ticker.get("markPrice") or ticker.get("lastPrice"), None)
        if price is not None:
            prices[symbol] = price
    return prices


def _orders_by_symbol(open_orders: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in open_orders:
        grouped.setdefault(str(order.get("symbol", "")).upper(), []).append(order)
    return grouped


def _trade_timestamp(trade: dict[str, Any]) -> float:
    for field in ("opened_at", "detected_at", "closed_at"):
        value = trade.get(field)
        if not value:
            continue
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return 0.0


def _timestamp_ms_to_iso(value: Any) -> str | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp / 1000.0, tz=UTC).isoformat()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()

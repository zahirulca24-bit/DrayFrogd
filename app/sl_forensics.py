from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any


FORENSIC_SCHEMA_VERSION = "sl_forensics_v1"
STOP_PRICE_CONFIRMATION_BPS = 5.0


SL_REASON_EXCHANGE_STOP = "exchange_stop_loss"
SL_REASON_STOP_PRICE_CONFIRMED = "stop_price_confirmed"
SL_REASON_FEE_DRAG_LOSS = "fee_drag_loss"
SL_REASON_OVERHELD_SCALPING = "overheld_scalping_sl"
SL_REASON_FORCED_RISK_CLOSE = "forced_risk_close"
SL_REASON_NON_SL_CLOSE = "non_sl_close"
SL_REASON_UNKNOWN = "stop_loss_or_risk_close"


def build_sl_forensics(trade: dict[str, Any], close_fields: dict[str, Any]) -> dict[str, Any]:
    """Build a structured post-close forensic payload for SL/loss review.

    The function is intentionally pure and side-effect free. It can be used by
    execution, reconciliation, journal repair scripts, or API serializers without
    touching exchange state. The payload is safe to persist inside
    ``trade_journal.exchange_metadata['sl_forensics']``.
    """

    metadata = _dict_value(trade.get("exchange_metadata"))
    sizing = _dict_value(metadata.get("position_sizing"))
    management = _dict_value(metadata.get("management") or trade.get("management"))

    entry = _number(close_fields.get("entry") or trade.get("entry") or trade.get("entry_price"))
    stop_loss = _number(close_fields.get("stop_loss") or trade.get("stop_loss"))
    take_profit = _number(close_fields.get("take_profit") or trade.get("take_profit"))
    exit_price = _number(close_fields.get("exit_price") or trade.get("exit_price"))
    quantity = _number(close_fields.get("quantity") or trade.get("remaining_quantity") or trade.get("quantity"))
    fees = _number(close_fields.get("fees") if "fees" in close_fields else trade.get("fees"))
    realized_pnl = _number(close_fields.get("realized_pnl") if "realized_pnl" in close_fields else trade.get("realized_pnl"))

    direction = str(close_fields.get("direction") or trade.get("direction") or "").lower().strip()
    trade_type = _resolve_trade_type(trade, close_fields, metadata, sizing, management)
    strategy_name = _resolve_strategy_name(trade, close_fields, metadata)

    price_risk_amount = _price_risk_amount(entry, stop_loss, quantity)
    gross_pnl = _gross_pnl(entry, exit_price, quantity, direction)
    if realized_pnl is None and gross_pnl is not None:
        realized_pnl = _round(gross_pnl - max(fees or 0.0, 0.0))

    stop_distance_bps = _distance_bps(entry, stop_loss)
    exit_to_stop_bps = _distance_bps(exit_price, stop_loss, denominator=entry)
    realized_r = _safe_ratio(realized_pnl, price_risk_amount)
    fee_drag_r = _safe_ratio(fees, price_risk_amount)
    held_seconds = _held_seconds(
        close_fields.get("opened_at") or trade.get("opened_at") or trade.get("detected_at"),
        close_fields.get("closed_at") or trade.get("closed_at"),
    )

    result = str(close_fields.get("result") or trade.get("result") or "").lower().strip()
    close_reason = str(close_fields.get("close_reason") or trade.get("close_reason") or "").strip()
    reason = classify_sl_reason(
        trade=trade,
        close_fields=close_fields,
        result=result,
        close_reason=close_reason,
        realized_pnl=realized_pnl,
        fees=fees,
        fee_drag_r=fee_drag_r,
        exit_to_stop_bps=exit_to_stop_bps,
        trade_type=trade_type,
        held_seconds=held_seconds,
    )

    return _compact(
        {
            "schema_version": FORENSIC_SCHEMA_VERSION,
            "symbol": str(close_fields.get("symbol") or trade.get("symbol") or "").upper().strip() or None,
            "strategy_name": strategy_name,
            "trade_type": trade_type,
            "direction": direction or None,
            "result": result or None,
            "sl_hit_reason": reason,
            "close_reason": close_reason or None,
            "entry": _round(entry),
            "stop_loss": _round(stop_loss),
            "take_profit": _round(take_profit),
            "exit_price": _round(exit_price),
            "quantity": _round(quantity),
            "gross_price_risk_amount": _round(price_risk_amount),
            "gross_pnl": _round(gross_pnl),
            "realized_pnl": _round(realized_pnl),
            "fees": _round(fees),
            "realized_r": _round(realized_r),
            "fee_drag_r": _round(fee_drag_r),
            "stop_distance_bps": _round(stop_distance_bps),
            "exit_to_stop_bps": _round(exit_to_stop_bps),
            "held_seconds": held_seconds,
            "held_minutes": _round(held_seconds / 60.0) if held_seconds is not None else None,
            "close_source": close_fields.get("close_source") or close_fields.get("source"),
            "forensic_flags": _forensic_flags(
                result=result,
                reason=reason,
                realized_pnl=realized_pnl,
                fee_drag_r=fee_drag_r,
                exit_to_stop_bps=exit_to_stop_bps,
                trade_type=trade_type,
                held_seconds=held_seconds,
            ),
        }
    )


def enrich_close_with_sl_forensics(trade: dict[str, Any], close_fields: dict[str, Any]) -> dict[str, Any]:
    """Return close fields with forensic metadata merged in."""

    forensic = build_sl_forensics(trade, close_fields)
    merged = dict(close_fields)
    metadata = _dict_value(trade.get("exchange_metadata"))
    metadata.update(_dict_value(close_fields.get("exchange_metadata")))
    metadata["sl_forensics"] = forensic
    merged["exchange_metadata"] = metadata
    if str(merged.get("result") or trade.get("result") or "").lower() == "sl" and not merged.get("sl_hit_reason"):
        merged["sl_hit_reason"] = forensic.get("sl_hit_reason")
    return merged


def classify_sl_reason(
    *,
    trade: dict[str, Any],
    close_fields: dict[str, Any],
    result: str,
    close_reason: str,
    realized_pnl: float | None,
    fees: float | None,
    fee_drag_r: float | None,
    exit_to_stop_bps: float | None,
    trade_type: str | None,
    held_seconds: int | None,
) -> str:
    explicit = str(close_fields.get("sl_hit_reason") or trade.get("sl_hit_reason") or "").strip()
    if explicit:
        return explicit

    reason_upper = close_reason.upper()
    close_source = str(close_fields.get("close_source") or close_fields.get("source") or "").lower()
    is_sl = result == "sl" or "STOP" in reason_upper or "SL" in reason_upper

    if not is_sl and realized_pnl is not None and realized_pnl >= 0:
        return SL_REASON_NON_SL_CLOSE

    # Specific evidence should win before generic source/reason labels. A close
    # can be reported by the exchange or risk module while the useful forensic
    # cause is still stop-price confirmation, fee drag, or an overheld scalping
    # trade.
    if exit_to_stop_bps is not None and exit_to_stop_bps <= STOP_PRICE_CONFIRMATION_BPS:
        return SL_REASON_STOP_PRICE_CONFIRMED
    if fee_drag_r is not None and fee_drag_r >= 0.50:
        return SL_REASON_FEE_DRAG_LOSS
    if realized_pnl is not None and realized_pnl < 0 and fees is not None and fees >= abs(realized_pnl) * 0.50:
        return SL_REASON_FEE_DRAG_LOSS
    if trade_type == "scalping" and held_seconds is not None and held_seconds > 30 * 60:
        return SL_REASON_OVERHELD_SCALPING
    if "FORCED" in reason_upper or "RISK" in reason_upper:
        return SL_REASON_FORCED_RISK_CLOSE
    if close_source in {"exchange", "exchange_close", "reconciliation", "bybit"} or "EXCHANGE" in reason_upper:
        return SL_REASON_EXCHANGE_STOP
    return SL_REASON_UNKNOWN


def _resolve_trade_type(
    trade: dict[str, Any],
    close_fields: dict[str, Any],
    metadata: dict[str, Any],
    sizing: dict[str, Any],
    management: dict[str, Any],
) -> str | None:
    raw = (
        close_fields.get("trade_type")
        or trade.get("trade_type")
        or metadata.get("trade_type")
        or sizing.get("trade_type")
        or management.get("trade_type")
    )
    value = str(raw or "").lower().strip()
    return value or None


def _resolve_strategy_name(trade: dict[str, Any], close_fields: dict[str, Any], metadata: dict[str, Any]) -> str:
    raw = close_fields.get("strategy_name") or close_fields.get("strategy") or trade.get("strategy_name") or trade.get("strategy")
    raw = raw or metadata.get("strategy_name") or metadata.get("strategy")
    value = str(raw or "unknown").strip()
    return value or "unknown"


def _forensic_flags(
    *,
    result: str,
    reason: str,
    realized_pnl: float | None,
    fee_drag_r: float | None,
    exit_to_stop_bps: float | None,
    trade_type: str | None,
    held_seconds: int | None,
) -> list[str]:
    flags: list[str] = []
    if result == "sl":
        flags.append("stop_loss_result")
    if realized_pnl is not None and realized_pnl < 0:
        flags.append("net_loss")
    if fee_drag_r is not None and fee_drag_r >= 0.25:
        flags.append("high_fee_drag")
    if exit_to_stop_bps is not None and exit_to_stop_bps <= STOP_PRICE_CONFIRMATION_BPS:
        flags.append("exit_near_stop")
    if trade_type == "scalping" and held_seconds is not None and held_seconds > 30 * 60:
        flags.append("overheld_scalping")
    if reason not in {SL_REASON_UNKNOWN, SL_REASON_NON_SL_CLOSE}:
        flags.append(reason)
    return flags


def _price_risk_amount(entry: float | None, stop_loss: float | None, quantity: float | None) -> float | None:
    if entry is None or stop_loss is None or quantity is None or quantity <= 0:
        return None
    return abs(entry - stop_loss) * quantity


def _gross_pnl(entry: float | None, exit_price: float | None, quantity: float | None, direction: str) -> float | None:
    if entry is None or exit_price is None or quantity is None or quantity <= 0:
        return None
    if direction == "long":
        return (exit_price - entry) * quantity
    if direction == "short":
        return (entry - exit_price) * quantity
    return None


def _distance_bps(first: float | None, second: float | None, denominator: float | None = None) -> float | None:
    denom = denominator if denominator is not None else first
    if first is None or second is None or denom is None or denom <= 0:
        return None
    return abs(first - second) / denom * 10000.0


def _held_seconds(opened_at: Any, closed_at: Any) -> int | None:
    opened = _parse_dt(opened_at)
    closed = _parse_dt(closed_at)
    if opened is None or closed is None:
        return None
    seconds = int((closed - opened).total_seconds())
    return max(seconds, 0)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 8)


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}

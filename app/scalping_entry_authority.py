from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from statistics import median
from typing import Any


APPROVE = "APPROVE"
MISSED = "MISSED"
REJECT = "REJECT"

REASON_APPROVED = "ENTRY_AUTHORITY_APPROVED"
REASON_PRICE_ESCAPED = "PRICE_ESCAPED_ENTRY_BAND"
REASON_INVALID_SIGNAL = "INVALID_SIGNAL"
REASON_NON_SCALPING = "NON_SCALPING_SIGNAL"
REASON_STALE_SIGNAL = "STALE_SIGNAL"
REASON_STALE_QUOTE = "STALE_MARKET_DATA"
REASON_SPREAD = "SPREAD_TOO_WIDE"
REASON_SPIKE = "ABNORMAL_SPIKE"
REASON_RR_DEGRADED = "RR_DEGRADED"
REASON_INVALID_GEOMETRY = "INVALID_ENTRY_GEOMETRY"
REASON_QUOTE_UNAVAILABLE = "QUOTE_UNAVAILABLE"

DEFAULT_MAX_SIGNAL_AGE_SECONDS = 180
DEFAULT_MAX_QUOTE_AGE_MS = 500
DEFAULT_MAX_SPREAD_BPS = 6.0
DEFAULT_MIN_NET_RR = 1.25
DEFAULT_MAX_ENTRY_DEVIATION_BPS = 5.0
DEFAULT_MAX_ENTRY_DEVIATION_R_FRACTION = 0.15
DEFAULT_SPIKE_TRUE_RANGE_MULTIPLE = 2.5
DEFAULT_FEE_BPS_PER_SIDE = 5.5


@dataclass(frozen=True)
class EntryAuthorityConfig:
    max_signal_age_seconds: int = DEFAULT_MAX_SIGNAL_AGE_SECONDS
    max_quote_age_ms: int = DEFAULT_MAX_QUOTE_AGE_MS
    max_spread_bps: float = DEFAULT_MAX_SPREAD_BPS
    min_net_rr: float = DEFAULT_MIN_NET_RR
    max_entry_deviation_bps: float = DEFAULT_MAX_ENTRY_DEVIATION_BPS
    max_entry_deviation_r_fraction: float = DEFAULT_MAX_ENTRY_DEVIATION_R_FRACTION
    spike_true_range_multiple: float = DEFAULT_SPIKE_TRUE_RANGE_MULTIPLE
    fee_bps_per_side: float = DEFAULT_FEE_BPS_PER_SIDE


def evaluate_entry_authority(
    signal: dict[str, Any],
    *,
    quote: dict[str, Any],
    now: datetime | None = None,
    recent_candles: list[dict[str, Any]] | None = None,
    config: EntryAuthorityConfig | None = None,
) -> dict[str, Any]:
    """Dry-run entry authority for scalping signals.

    This worker never submits an order. It converts one candidate signal plus one
    executable quote into an audit decision: APPROVE, MISSED, or REJECT.
    """

    cfg = config or EntryAuthorityConfig()
    current = _as_utc(now or datetime.now(UTC))
    normalized = _normalize_signal(signal)
    if normalized is None:
        return _decision(REJECT, REASON_INVALID_SIGNAL, signal=signal, quote=quote)

    if normalized["trade_type"] != "scalping":
        return _decision(REJECT, REASON_NON_SCALPING, signal=normalized, quote=quote)

    if normalized["status"] != "active":
        return _decision(REJECT, REASON_INVALID_SIGNAL, signal=normalized, quote=quote)

    age_seconds = _age_seconds(normalized.get("detected_at"), current)
    if age_seconds is not None and age_seconds > cfg.max_signal_age_seconds:
        return _decision(
            MISSED,
            REASON_STALE_SIGNAL,
            signal=normalized,
            quote=quote,
            evidence={"signal_age_seconds": age_seconds, "max_signal_age_seconds": cfg.max_signal_age_seconds},
        )

    market = _normalize_quote(quote, normalized["direction"], current)
    if market is None:
        return _decision(REJECT, REASON_QUOTE_UNAVAILABLE, signal=normalized, quote=quote)

    if market["quote_age_ms"] > cfg.max_quote_age_ms:
        return _decision(
            REJECT,
            REASON_STALE_QUOTE,
            signal=normalized,
            quote=quote,
            evidence={"quote_age_ms": market["quote_age_ms"], "max_quote_age_ms": cfg.max_quote_age_ms},
        )

    spread_bps = market["spread_bps"]
    if spread_bps is None or spread_bps > cfg.max_spread_bps + 1e-9:
        return _decision(
            REJECT,
            REASON_SPREAD,
            signal=normalized,
            quote=quote,
            evidence={"spread_bps": spread_bps, "max_spread_bps": cfg.max_spread_bps},
        )

    spike = detect_abnormal_spike(recent_candles or [], cfg.spike_true_range_multiple)
    if spike.get("abnormal"):
        return _decision(REJECT, REASON_SPIKE, signal=normalized, quote=quote, evidence={"spike": spike})

    band = _entry_band(normalized, cfg)
    if band is None:
        return _decision(REJECT, REASON_INVALID_GEOMETRY, signal=normalized, quote=quote)

    executable_price = market["executable_price"]
    if not (band["allowed_entry_min"] <= executable_price <= band["allowed_entry_max"]):
        return _decision(
            MISSED,
            REASON_PRICE_ESCAPED,
            signal=normalized,
            quote=quote,
            evidence={**market, **band, **_deviation(normalized["entry"], executable_price)},
        )

    gross = _risk_reward(
        direction=normalized["direction"],
        entry=executable_price,
        stop_loss=normalized["stop_loss"],
        take_profit=normalized["take_profit"],
    )
    if gross is None:
        return _decision(REJECT, REASON_INVALID_GEOMETRY, signal=normalized, quote=quote, evidence={**market, **band})

    fee_fraction = max(float(cfg.fee_bps_per_side), 0.0) / 10_000.0
    round_trip_cost = executable_price * fee_fraction * 2.0
    net_reward_distance = gross["reward_distance"] - round_trip_cost
    net_rr = net_reward_distance / gross["risk_distance"] if gross["risk_distance"] > 0 else 0.0
    if net_rr + 1e-9 < cfg.min_net_rr:
        return _decision(
            REJECT,
            REASON_RR_DEGRADED,
            signal=normalized,
            quote=quote,
            evidence={
                **market,
                **band,
                "gross_rr": gross["risk_reward"],
                "net_rr": net_rr,
                "min_net_rr": cfg.min_net_rr,
                "estimated_round_trip_cost": round_trip_cost,
            },
        )

    limit_price = band["allowed_entry_max"] if normalized["direction"] == "long" else band["allowed_entry_min"]
    return _decision(
        APPROVE,
        REASON_APPROVED,
        signal=normalized,
        quote=quote,
        evidence={
            **market,
            **band,
            **_deviation(normalized["entry"], executable_price),
            "gross_rr": gross["risk_reward"],
            "net_rr": net_rr,
            "min_net_rr": cfg.min_net_rr,
            "selected_order_type": "MARKETABLE_LIMIT_IOC",
            "limit_price": round(limit_price, 8),
            "time_in_force": "IOC",
        },
    )


def evaluate_entry_authority_from_client(
    client: Any,
    signal: dict[str, Any],
    *,
    now: datetime | None = None,
    config: EntryAuthorityConfig | None = None,
) -> dict[str, Any]:
    """Fetch live evidence and run the dry-run entry authority.

    No exchange order endpoint is called here.
    """

    symbol = str(signal.get("symbol") or "").upper().strip()
    if not symbol:
        return _decision(REJECT, REASON_INVALID_SIGNAL, signal=signal, quote={})

    quote_result = _fetch_quote(client, symbol)
    candles: list[dict[str, Any]] = []
    candle_method = getattr(client, "safe_fetch_recent_candles", None)
    if callable(candle_method):
        ok, raw_candles, _error = candle_method(symbol=symbol, interval="1", limit=35)
        if ok and isinstance(raw_candles, list):
            candles = raw_candles

    return evaluate_entry_authority(
        signal,
        quote=quote_result,
        now=now,
        recent_candles=candles,
        config=config,
    )


def detect_abnormal_spike(candles: list[dict[str, Any]], multiple: float = DEFAULT_SPIKE_TRUE_RANGE_MULTIPLE) -> dict[str, Any]:
    normalized = [_normalize_candle(item) for item in candles]
    normalized = [item for item in normalized if item is not None]
    if len(normalized) < 6:
        return {"abnormal": False, "reason": "insufficient_candles", "latest_true_range": None, "median_true_range": None}

    latest = normalized[-1]
    history = normalized[:-1][-30:]
    ranges = [item["high"] - item["low"] for item in history if item["high"] >= item["low"]]
    ranges = [value for value in ranges if isfinite(value) and value > 0]
    latest_range = latest["high"] - latest["low"]
    if not ranges or latest_range <= 0:
        return {"abnormal": False, "reason": "true_range_unavailable", "latest_true_range": latest_range, "median_true_range": None}

    median_range = median(ranges)
    abnormal = median_range > 0 and latest_range > median_range * float(multiple)
    return {
        "abnormal": bool(abnormal),
        "reason": "abnormal_true_range" if abnormal else "normal",
        "latest_true_range": latest_range,
        "median_true_range": median_range,
        "multiple": multiple,
        "observed_multiple": latest_range / median_range if median_range > 0 else None,
    }


def _fetch_quote(client: Any, symbol: str) -> dict[str, Any]:
    method = getattr(client, "safe_fetch_ticker", None)
    fetched_at = datetime.now(UTC).isoformat()
    if callable(method):
        ok, ticker, error = method(symbol=symbol)
        if not ok or not ticker:
            return {"ok": False, "error": error or "Ticker unavailable", "symbol": symbol, "fetched_at": fetched_at}
        return {"ok": True, "symbol": symbol, "ticker": ticker, "fetched_at": fetched_at}

    return {"ok": False, "error": "safe_fetch_ticker unavailable", "symbol": symbol, "fetched_at": fetched_at}


def _normalize_signal(signal: dict[str, Any]) -> dict[str, Any] | None:
    try:
        symbol = str(signal.get("symbol") or "").upper().strip()
        direction = str(signal.get("direction") or "").lower().strip()
        entry = float(signal.get("entry"))
        stop_loss = float(signal.get("stop_loss"))
        take_profit = float(signal.get("take_profit"))
    except (TypeError, ValueError):
        return None

    trade_type = str(signal.get("trade_type") or "").lower().strip()
    status = str(signal.get("status") or "").lower().strip()
    if not symbol or direction not in {"long", "short"} or not all(_positive(value) for value in (entry, stop_loss, take_profit)):
        return None

    return {
        **signal,
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "trade_type": trade_type,
        "status": status,
    }


def _normalize_quote(quote: dict[str, Any], direction: str, now: datetime) -> dict[str, Any] | None:
    if not quote.get("ok", True):
        return None
    ticker = quote.get("ticker") if isinstance(quote.get("ticker"), dict) else quote
    bid = _positive_float(ticker.get("bid1Price") or ticker.get("bid"))
    ask = _positive_float(ticker.get("ask1Price") or ticker.get("ask"))
    fallback = _positive_float(ticker.get("markPrice") or ticker.get("lastPrice") or ticker.get("price"))
    executable = ask if direction == "long" else bid
    if executable is None:
        executable = fallback
    if executable is None:
        return None

    spread_bps = None
    if bid is not None and ask is not None and ask >= bid:
        midpoint = (bid + ask) / 2.0
        if midpoint > 0:
            spread_bps = ((ask - bid) / midpoint) * 10_000.0

    quote_time = _parse_time(
        quote.get("timestamp")
        or quote.get("fetched_at")
        or ticker.get("time")
        or ticker.get("timestamp")
    )
    quote_age_ms = 0 if quote_time is None else max((now - quote_time).total_seconds() * 1000.0, 0.0)
    return {
        "live_bid": bid,
        "live_ask": ask,
        "executable_price": executable,
        "spread_bps": spread_bps,
        "quote_age_ms": quote_age_ms,
    }


def _entry_band(signal: dict[str, Any], cfg: EntryAuthorityConfig) -> dict[str, float] | None:
    rr = _risk_reward(
        direction=signal["direction"],
        entry=signal["entry"],
        stop_loss=signal["stop_loss"],
        take_profit=signal["take_profit"],
    )
    if rr is None:
        return None

    explicit_min = _positive_float(signal.get("allowed_entry_min"))
    explicit_max = _positive_float(signal.get("allowed_entry_max"))
    if explicit_min is not None and explicit_max is not None and explicit_min <= explicit_max:
        return {"allowed_entry_min": explicit_min, "allowed_entry_max": explicit_max, "band_source": "signal"}

    entry = signal["entry"]
    r_cap = rr["risk_distance"] * cfg.max_entry_deviation_r_fraction
    bps_cap = entry * (cfg.max_entry_deviation_bps / 10_000.0)
    deviation = min(r_cap, bps_cap)
    if deviation <= 0:
        return None
    if signal["direction"] == "long":
        return {
            "allowed_entry_min": round(entry, 8),
            "allowed_entry_max": round(entry + deviation, 8),
            "max_entry_deviation": deviation,
            "band_source": "derived_from_signal_entry",
        }
    return {
        "allowed_entry_min": round(entry - deviation, 8),
        "allowed_entry_max": round(entry, 8),
        "max_entry_deviation": deviation,
        "band_source": "derived_from_signal_entry",
    }


def _risk_reward(*, direction: str, entry: float, stop_loss: float, take_profit: float) -> dict[str, float] | None:
    if not all(_positive(value) for value in (entry, stop_loss, take_profit)):
        return None
    if direction == "long":
        if not stop_loss < entry < take_profit:
            return None
        risk_distance = entry - stop_loss
        reward_distance = take_profit - entry
    elif direction == "short":
        if not take_profit < entry < stop_loss:
            return None
        risk_distance = stop_loss - entry
        reward_distance = entry - take_profit
    else:
        return None
    if risk_distance <= 0 or reward_distance <= 0:
        return None
    return {"risk_distance": risk_distance, "reward_distance": reward_distance, "risk_reward": reward_distance / risk_distance}


def _deviation(planned_entry: float, executable_price: float) -> dict[str, float]:
    absolute = executable_price - planned_entry
    bps = (absolute / planned_entry) * 10_000.0 if planned_entry > 0 else 0.0
    return {"actual_entry_deviation": absolute, "entry_deviation_bps": bps}


def _decision(
    decision: str,
    reason_code: str,
    *,
    signal: dict[str, Any],
    quote: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": decision == APPROVE,
        "worker": "ScalpingEntryAuthorityWorkerV1",
        "mode": "dry_run_no_order_submission",
        "decision": decision,
        "reason_code": reason_code,
        "symbol": signal.get("symbol"),
        "direction": signal.get("direction"),
        "signal_entry": signal.get("entry"),
        "evidence": evidence or {},
        "quote": quote,
    }


def _normalize_candle(item: dict[str, Any]) -> dict[str, float] | None:
    try:
        high = float(item.get("high"))
        low = float(item.get("low"))
    except (TypeError, ValueError):
        return None
    if not isfinite(high) or not isfinite(low) or high < low:
        return None
    return {"high": high, "low": low}


def _age_seconds(value: Any, now: datetime) -> float | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return max((now - parsed).total_seconds(), 0.0)


def _parse_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        return datetime.fromtimestamp(numeric, tz=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _positive_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if _positive(numeric) else None


def _positive(value: float) -> bool:
    return isfinite(value) and value > 0

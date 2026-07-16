from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from math import isfinite
from threading import Lock
from typing import Any

from app.bot_controls import get_execution_mode
from app.config import settings
from app.execution_core import _build_execution_key
from app.journal import get_trade_by_execution_key
from app.risk import extract_account_equity, refresh_risk_state, validate_trade
from app.trading_costs import calculate_cost_adjusted_geometry


_APPROVAL_VERSION = 1
_used_decisions: dict[str, datetime] = {}
_approval_lock = Lock()


def issue_execution_approval(
    client: Any,
    signal: dict[str, Any],
    *,
    auto_triggered: bool = False,
    now: datetime | None = None,
    wallet: dict[str, Any] | None = None,
    positions: list[dict[str, Any]] | None = None,
    account_equity: float | None = None,
    identity_signal: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    risk_state: dict[str, Any] | None = None,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    """Issue a short-lived, signal-bound risk approval.

    This is the only pre-order authority used by the public execution API. It
    fails closed when wallet, positions, signal lifecycle, portfolio state or
    fee-adjusted economics cannot be verified.
    """

    current = _as_utc(now)
    normalized = _normalize_signal(signal)
    if normalized is None:
        return _reject("INVALID_SIGNAL", "Invalid execution signal payload")
    if normalized["status"] != "active":
        return _reject("SIGNAL_NOT_ACTIVE", "Signal is not active")
    if normalized["signal_state"] not in {None, "ACTIVE"}:
        return _reject("SIGNAL_NOT_ACTIVE", f"Signal state is {normalized['signal_state']}")
    if normalized["is_executable"] is False:
        return _reject("SIGNAL_NOT_EXECUTABLE", "Signal is explicitly marked non-executable")
    if auto_triggered and normalized["primary_signal"] is False:
        return _reject("SIGNAL_NOT_PRIMARY", "Automatic execution requires a primary signal")

    lifecycle = _validate_signal_lifecycle(normalized, current)
    if lifecycle is not None:
        return lifecycle

    mode = str(execution_mode or get_execution_mode()).lower().strip()
    identity = _normalize_signal(identity_signal or signal)
    if identity is None:
        return _reject("INVALID_SIGNAL_IDENTITY", "Execution signal identity is invalid")
    execution_key = _build_execution_key(identity, mode)
    # Duplicate execution, same-symbol cooldown, daily count and risk capacity
    # are enforced atomically by reserve_execution_capacity after this signed
    # decision is consumed. A pre-approval Journal query would introduce a
    # second database dependency and a time-of-check/time-of-use race.
    resolved_positions = positions
    if resolved_positions is None:
        ok_positions, resolved_positions, positions_error = client.safe_fetch_positions()
        if not ok_positions:
            return _reject("POSITION_STATE_UNAVAILABLE", positions_error or "Position data unavailable")
    if _has_open_symbol(resolved_positions, normalized["symbol"]):
        return _reject("SYMBOL_ALREADY_ACTIVE", f"{normalized['symbol']} already has an exchange position")

    resolved_wallet = wallet
    if resolved_wallet is None:
        ok_wallet, resolved_wallet, wallet_error = client.safe_fetch_wallet_balance()
        if not ok_wallet or resolved_wallet is None:
            return _reject("WALLET_STATE_UNAVAILABLE", wallet_error or "Wallet balance unavailable")
    resolved_equity = account_equity if account_equity is not None else extract_account_equity(resolved_wallet)
    if resolved_equity is None:
        return _reject("EQUITY_UNAVAILABLE", "Fresh account equity is unavailable")

    resolved_risk_state = risk_state or refresh_risk_state(account_equity=resolved_equity, now=current)
    resolved_validation = validation or validate_trade(normalized, account_equity=resolved_equity)
    if not resolved_validation.get("allowed"):
        return _reject(
            "RISK_POLICY_REJECTED",
            str(resolved_validation.get("reason") or "Risk validation failed"),
            risk_state=resolved_risk_state,
        )

    economics = calculate_cost_adjusted_geometry(
        direction=normalized["direction"],
        entry=normalized["entry"],
        stop_loss=normalized["stop_loss"],
        take_profit=normalized["take_profit"],
        quantity=1.0,
        fee_bps=settings.execution_taker_fee_bps,
        slippage_bps=settings.execution_slippage_bps,
    )
    minimum_net_rr = float(resolved_validation.get("min_risk_reward") or 0.0)
    if economics is None or economics["net_reward"] <= 0:
        return _reject("FEE_VIABILITY_REJECTED", "Estimated fees/slippage eliminate the target reward")
    if economics["net_risk_reward"] + 1e-9 < minimum_net_rr:
        return _reject(
            "FEE_VIABILITY_REJECTED",
            (
                f"Fee-adjusted RR {economics['net_risk_reward']:.4f} is below "
                f"the required {minimum_net_rr:.4f}"
            ),
            economics=economics,
        )

    secret = _approval_secret()
    if secret is None:
        return _reject("RISK_APPROVAL_SECRET_UNAVAILABLE", "Risk approval signing secret is unavailable")

    decision_id = secrets.token_urlsafe(18)
    expires_at = current + timedelta(seconds=max(int(settings.risk_approval_ttl_seconds), 1))
    decision = {
        "version": _APPROVAL_VERSION,
        "decision_id": decision_id,
        "execution_key": execution_key,
        "signal_fingerprint": _signal_fingerprint(normalized, mode),
        "symbol": normalized["symbol"],
        "trade_type": normalized["trade_type"],
        "direction": normalized["direction"],
        "execution_mode": mode,
        "risk_amount": float(resolved_validation.get("risk_amount") or 0.0),
        "risk_per_trade": float(resolved_validation.get("risk_per_trade") or 0.0),
        "leverage_cap": float(resolved_validation.get("leverage_cap") or 0.0),
        "exposure_cap": float(resolved_validation.get("exposure_cap") or 0.0),
        "min_net_risk_reward": minimum_net_rr,
        "estimated_net_risk_reward": float(economics["net_risk_reward"]),
        "account_equity": resolved_equity,
        "auto_triggered": bool(auto_triggered),
        "issued_at": current.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    return {
        "allowed": True,
        "reason": "",
        "error": None,
        "token": _encode_token(decision, secret),
        "decision": decision,
        "validation": resolved_validation,
        "risk_state": resolved_risk_state,
        "economics": economics,
    }


def verify_risk_approval(
    token: str | None,
    signal: dict[str, Any],
    *,
    execution_mode: str | None = None,
    consume: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _as_utc(now)
    secret = _approval_secret()
    if secret is None:
        return _reject("RISK_APPROVAL_SECRET_UNAVAILABLE", "Risk approval signing secret is unavailable")
    if not token:
        return _reject("RISK_APPROVAL_REQUIRED", "A signed Risk Engine approval is required")

    decision = _decode_token(token, secret)
    if decision is None:
        return _reject("RISK_APPROVAL_INVALID", "Risk approval signature or payload is invalid")
    if int(decision.get("version") or 0) != _APPROVAL_VERSION:
        return _reject("RISK_APPROVAL_INVALID", "Risk approval version is unsupported")

    expires_at = _parse_time(decision.get("expires_at"))
    if expires_at is None or current >= expires_at:
        return _reject("RISK_APPROVAL_EXPIRED", "Risk approval has expired")

    normalized = _normalize_signal(signal)
    if normalized is None:
        return _reject("RISK_APPROVAL_SIGNAL_MISMATCH", "Execution signal is invalid")
    mode = str(execution_mode or get_execution_mode()).lower().strip()
    if not hmac.compare_digest(
        str(decision.get("signal_fingerprint") or ""),
        _signal_fingerprint(normalized, mode),
    ):
        return _reject("RISK_APPROVAL_SIGNAL_MISMATCH", "Risk approval does not match this signal")
    if str(decision.get("execution_mode") or "") != mode:
        return _reject("RISK_APPROVAL_MODE_MISMATCH", "Risk approval execution mode changed")

    decision_id = str(decision.get("decision_id") or "")
    if not decision_id:
        return _reject("RISK_APPROVAL_INVALID", "Risk approval decision ID is missing")

    with _approval_lock:
        _purge_consumed(current)
        if decision_id in _used_decisions:
            return _reject("RISK_APPROVAL_ALREADY_USED", "Risk approval has already been consumed")
        if consume:
            _used_decisions[decision_id] = expires_at

    return {"allowed": True, "reason": "", "error": None, "decision": decision}


def _validate_signal_lifecycle(normalized: dict[str, Any], current: datetime) -> dict[str, Any] | None:
    expires_at = _parse_time(normalized.get("expires_at"))
    if expires_at is not None and current >= expires_at:
        return _reject("SIGNAL_EXPIRED", "Signal expiry timestamp has passed")

    if normalized.get("auto_triggered") and not normalized.get("detected_at"):
        return _reject("SIGNAL_TIMESTAMP_REQUIRED", "Automatic execution requires a detected_at timestamp")
    detected_at = _parse_time(normalized.get("detected_at"))
    if normalized.get("detected_at") and detected_at is None:
        return _reject("SIGNAL_TIMESTAMP_INVALID", "Signal detected_at timestamp is invalid")
    if detected_at is not None and normalized.get("auto_triggered"):
        max_age = max(int(settings.risk_signal_max_age_seconds), 1)
        age_seconds = (current - detected_at).total_seconds()
        if age_seconds < -5:
            return _reject("SIGNAL_TIMESTAMP_INVALID", "Signal detected_at timestamp is in the future")
        if age_seconds > max_age:
            return _reject(
                "SIGNAL_STALE",
                f"Signal age {age_seconds:.0f}s exceeds the {max_age}s execution limit",
            )
    return None


def _normalize_signal(signal: dict[str, Any]) -> dict[str, Any] | None:
    try:
        direction = str(signal.get("direction") or "").lower().strip()
        symbol = str(signal.get("symbol") or "").upper().strip()
        trade_type = str(signal.get("trade_type") or "").lower().strip()
        entry = float(signal.get("entry"))
        stop_loss = float(signal.get("stop_loss"))
        take_profit = float(signal.get("take_profit"))
    except (TypeError, ValueError):
        return None
    if not symbol or direction not in {"long", "short"} or trade_type not in {"scalping", "intraday"}:
        return None
    if not all(isfinite(value) and value > 0 for value in (entry, stop_loss, take_profit)):
        return None
    return {
        "symbol": symbol,
        "strategy_name": str(signal.get("strategy_name") or signal.get("strategy") or "unknown"),
        "trade_type": trade_type,
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": signal.get("risk_reward"),
        "detected_at": signal.get("detected_at"),
        "expires_at": signal.get("expires_at"),
        "status": str(signal.get("status") or "active").lower().strip(),
        "signal_state": str(signal.get("signal_state") or "").upper().strip() or None,
        "is_executable": signal.get("is_executable") if "is_executable" in signal else None,
        "primary_signal": signal.get("primary_signal") if "primary_signal" in signal else None,
        "auto_triggered": bool(signal.get("auto_triggered")),
    }


def _signal_fingerprint(signal: dict[str, Any], mode: str) -> str:
    payload = {
        "mode": str(mode or "").lower().strip(),
        "symbol": signal["symbol"],
        "strategy": str(signal.get("strategy_name") or "unknown").lower().strip(),
        "trade_type": signal["trade_type"],
        "direction": signal["direction"],
        "entry": format(float(signal["entry"]), ".12g"),
        "stop_loss": format(float(signal["stop_loss"]), ".12g"),
        "take_profit": format(float(signal["take_profit"]), ".12g"),
        "detected_at": str(signal.get("detected_at") or ""),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _has_open_symbol(positions: list[dict[str, Any]], symbol: str) -> bool:
    for position in positions:
        try:
            size = float(position.get("size") or 0.0)
        except (TypeError, ValueError):
            continue
        if str(position.get("symbol") or "").upper().strip() == symbol and size > 0:
            return True
    return False


def _approval_secret() -> bytes | None:
    value = str(settings.session_secret or "").strip()
    if not value:
        if str(settings.app_env or "").lower() == "production":
            return None
        value = "dayfrogd-development-risk-approval"
    return hashlib.sha256(f"{value}|dayfrogd-risk-approval-v1".encode("utf-8")).digest()


def _encode_token(decision: dict[str, Any], secret: bytes) -> str:
    raw = json.dumps(decision, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload = _b64encode(raw)
    signature = _b64encode(hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def _decode_token(token: str, secret: bytes) -> dict[str, Any] | None:
    try:
        payload, signature = token.split(".", 1)
        expected = _b64encode(hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        decoded = json.loads(_b64decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _purge_consumed(current: datetime) -> None:
    expired = [decision_id for decision_id, expiry in _used_decisions.items() if current >= expiry]
    for decision_id in expired:
        _used_decisions.pop(decision_id, None)


def _reject(code: str, reason: str, **evidence: Any) -> dict[str, Any]:
    return {
        "allowed": False,
        "reason": reason,
        "error": code,
        **evidence,
    }

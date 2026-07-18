from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from functools import wraps
from threading import RLock
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.database import SessionLocal
from app.exchange import get_exchange_client
from app.journal import append_trade_event, log_bot_event
from app.ledger_audit import get_account_ledger_audit
from app.models import RiskRuntimeState, TradeJournal

BDT = ZoneInfo("Asia/Dhaka")
_AUTHORITY_CACHE_SECONDS = 10.0
_INSTALLED = False
_CACHE_LOCK = RLock()
_AUTHORITY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_ORIGINAL_RISK_REFRESH: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_EXECUTE_SIGNAL: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_PRIVATE_CALLBACK: Callable[..., None] | None = None

EXPECTED_BLOCK_CODES = {
    "DUPLICATE_EXECUTION",
    "SYMBOL_ALREADY_ACTIVE",
    "ACTIVE_TRADE_LIMIT_REACHED",
    "DYNAMIC_RISK_CAPACITY_EXCEEDED",
    "SYMBOL_REENTRY_COOLDOWN",
    "DAILY_LOSS_AUTHORITY_UNAVAILABLE",
    "DAILY_LOSS_CIRCUIT_BREAKER",
    "RISK_POLICY_REJECTED",
    "FEE_VIABILITY_REJECTED",
    "SPREAD_GATE_REJECTED",
}


def install() -> None:
    """Install bounded P0 runtime truth hooks before the public app imports APIs."""

    global _INSTALLED, _ORIGINAL_RISK_REFRESH, _ORIGINAL_EXECUTE_SIGNAL, _ORIGINAL_PRIVATE_CALLBACK
    if _INSTALLED:
        return

    import app.authoritative_risk_engine as authoritative_risk_engine
    import app.execution as execution
    import app.execution_service as execution_service
    import app.readiness as readiness
    import app.risk as risk
    from app.bybit_websocket import BybitWebSocketService

    original_risk_refresh = risk.refresh_risk_state
    _ORIGINAL_RISK_REFRESH = original_risk_refresh

    @wraps(original_risk_refresh)
    def authoritative_refresh_risk_state(
        account_equity: float | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        snapshot = original_risk_refresh(account_equity=account_equity, now=now)
        try:
            authority = get_daily_loss_authority()
            return apply_daily_loss_authority(
                snapshot,
                authority,
                account_equity=account_equity,
            )
        except Exception as exc:  # pragma: no cover - fail-safe observability
            enriched = dict(snapshot)
            enriched.update(
                daily_loss_authority_status="unavailable",
                daily_loss_authority_source="bybit_account_transaction_log",
                daily_loss_authority_error=str(exc),
            )
            return enriched

    risk.refresh_risk_state = authoritative_refresh_risk_state
    execution_service.refresh_risk_state = authoritative_refresh_risk_state
    authoritative_risk_engine.refresh_risk_state = authoritative_refresh_risk_state

    original_execute_signal = execution.execute_signal
    _ORIGINAL_EXECUTE_SIGNAL = original_execute_signal

    @wraps(original_execute_signal)
    def execute_signal_with_daily_loss_authority(
        client: Any,
        signal: dict[str, Any],
        auto_triggered: bool = False,
    ) -> dict[str, Any]:
        authority = get_daily_loss_authority(client=client, force=True)
        if not authority.get("ok"):
            return {
                "ok": False,
                "error": "DAILY_LOSS_AUTHORITY_UNAVAILABLE",
                "detail": authority.get("error") or "Bybit daily loss authority is unavailable",
                "daily_loss_authority": authority,
            }

        wallet_ok, wallet, wallet_error = client.safe_fetch_wallet_balance()
        if not wallet_ok or wallet is None:
            return {
                "ok": False,
                "error": "WALLET_STATE_UNAVAILABLE",
                "detail": wallet_error or "Wallet balance unavailable",
                "daily_loss_authority": authority,
            }

        account_equity = risk.extract_account_equity(wallet)
        if account_equity is None:
            return {
                "ok": False,
                "error": "EQUITY_UNAVAILABLE",
                "detail": "Fresh account equity is unavailable",
                "daily_loss_authority": authority,
            }

        risk_state = authoritative_refresh_risk_state(account_equity=account_equity)
        if risk_state.get("circuit_breaker_active"):
            return {
                "ok": False,
                "error": "DAILY_LOSS_CIRCUIT_BREAKER",
                "detail": risk_state.get("circuit_breaker_reason") or "Daily loss circuit breaker is active",
                "daily_loss_authority": authority,
                "risk_state": risk_state,
            }

        result = original_execute_signal(client, signal, auto_triggered)
        return normalize_execution_block(result)

    execution.execute_signal = execute_signal_with_daily_loss_authority

    original_readiness = readiness.get_readiness_status

    @wraps(original_readiness)
    def readiness_with_private_ws_truth() -> dict[str, Any]:
        payload = original_readiness()
        from app.bybit_websocket import websocket_service

        ws_status = websocket_service.get_status()
        return enrich_readiness_with_ws(payload, ws_status)

    readiness.get_readiness_status = readiness_with_private_ws_truth

    original_private_callback = BybitWebSocketService._private_callback
    _ORIGINAL_PRIVATE_CALLBACK = original_private_callback

    @wraps(original_private_callback)
    def private_callback_with_identity_persistence(self: Any, message: dict[str, Any]) -> None:
        original_private_callback(self, message)
        if str(message.get("topic") or "").startswith("execution"):
            records = message.get("data") if isinstance(message.get("data"), list) else []
            persist_private_execution_records(records)

    BybitWebSocketService._private_callback = private_callback_with_identity_persistence

    # Background worker imports after package initialization in production, but
    # importing here is safe and ensures all expected policy/guard rejections are
    # recorded as bounded blocks instead of AUTO_EXECUTION_FAILED incidents.
    try:
        import app.background_worker as background_worker

        background_worker.EXPECTED_EXECUTION_BLOCKS.update(EXPECTED_BLOCK_CODES)
    except Exception:
        pass

    _INSTALLED = True


def get_daily_loss_authority(*, client: Any | None = None, force: bool = False) -> dict[str, Any]:
    resolved_client = client or get_exchange_client(__import__("app.bot_controls", fromlist=["get_execution_mode"]).get_execution_mode())
    mode = str(getattr(resolved_client, "mode", "demo") or "demo").lower()
    day = datetime.now(BDT).date().isoformat()
    key = f"{mode}:{day}"
    now_monotonic = time.monotonic()

    if not force:
        with _CACHE_LOCK:
            cached = _AUTHORITY_CACHE.get(key)
            if cached and now_monotonic - cached[0] <= _AUTHORITY_CACHE_SECONDS:
                return dict(cached[1])

    audit = get_account_ledger_audit(resolved_client, bdt_date=day)
    if not audit.get("ok"):
        result = {
            "ok": False,
            "date": day,
            "mode": mode,
            "source": "bybit_account_transaction_log",
            "error": audit.get("error") or "Bybit transaction log query failed",
        }
    else:
        summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
        result = {
            "ok": True,
            "date": day,
            "mode": mode,
            "source": "bybit_account_transaction_log",
            "trade_net": _number(summary.get("trade_change")) or 0.0,
            "account_net": _number(summary.get("net_change")) or 0.0,
            "fees": abs(_number(summary.get("fees")) or 0.0),
            "funding": _number(summary.get("funding")) or 0.0,
            "record_count": int(summary.get("record_count") or 0),
            "trade_count": int(summary.get("trade_count") or 0),
            "captured_at": datetime.now(UTC).isoformat(),
            "error": None,
        }

    with _CACHE_LOCK:
        _AUTHORITY_CACHE[key] = (now_monotonic, dict(result))
    return result


def apply_daily_loss_authority(
    snapshot: dict[str, Any],
    authority: dict[str, Any],
    *,
    account_equity: float | None,
) -> dict[str, Any]:
    enriched = dict(snapshot)
    enriched.update(
        daily_loss_authority_status="authoritative" if authority.get("ok") else "unavailable",
        daily_loss_authority_source=authority.get("source") or "bybit_account_transaction_log",
        daily_loss_authority_error=authority.get("error"),
    )
    if not authority.get("ok"):
        return enriched

    trade_net = _number(authority.get("trade_net")) or 0.0
    account_net = _number(authority.get("account_net")) or 0.0
    day_start_equity = _positive(enriched.get("day_start_equity"))
    if day_start_equity is None:
        current_equity = _positive(account_equity)
        if current_equity is not None:
            reconstructed = current_equity - account_net
            day_start_equity = reconstructed if reconstructed > 0 else current_equity

    from app import risk

    limit_ratio = float(risk.DAILY_NET_LOSS_LIMIT_RATIO)
    loss_limit = (day_start_equity or 0.0) * limit_ratio
    threshold_hit = bool(day_start_equity and trade_net <= -loss_limit + 1e-9)
    capacity = risk.calculate_risk_capacity(
        day_start_equity=day_start_equity or 0.0,
        realized_pnl_today=trade_net,
        live_risk=float(enriched.get("live_risk") or 0.0),
    )

    reason = (
        f"Authoritative Bybit daily trade net loss limit reached: {trade_net:.2f} USDT <= -{loss_limit:.2f} USDT"
        if threshold_hit
        else None
    )

    db = SessionLocal()
    activated = False
    try:
        row = db.query(RiskRuntimeState).filter(RiskRuntimeState.id == 1).first()
        if row is not None:
            was_active = bool(row.circuit_breaker_active)
            row.realized_pnl_today = trade_net
            row.base_risk_pool = capacity["base_risk_pool"]
            row.effective_risk_pool = capacity["effective_risk_pool"]
            row.available_risk = capacity["available_risk"]
            if day_start_equity and not row.day_start_equity:
                row.day_start_equity = day_start_equity
            if threshold_hit:
                row.circuit_breaker_active = True
                row.circuit_breaker_reason = reason
            activated = bool(row.circuit_breaker_active) and not was_active
            db.commit()
            circuit_active = bool(row.circuit_breaker_active)
            circuit_reason = row.circuit_breaker_reason
        else:
            circuit_active = bool(enriched.get("circuit_breaker_active")) or threshold_hit
            circuit_reason = reason or enriched.get("circuit_breaker_reason")
    finally:
        db.close()

    enriched.update(
        realized_pnl_today=trade_net,
        realized_pnl_source="bybit_account_transaction_log",
        authoritative_trade_net=trade_net,
        authoritative_account_net=account_net,
        authoritative_fees=_number(authority.get("fees")) or 0.0,
        authoritative_funding=_number(authority.get("funding")) or 0.0,
        daily_net_loss_limit_amount=loss_limit,
        base_risk_pool=capacity["base_risk_pool"],
        effective_risk_pool=capacity["effective_risk_pool"],
        available_risk=capacity["available_risk"],
        circuit_breaker_active=circuit_active,
        circuit_breaker_reason=circuit_reason,
    )

    if circuit_active:
        from app.bot_controls import stop_bot

        stop_bot()
    if activated:
        _safe_bot_event(
            "DAILY_NET_LOSS_CIRCUIT_BREAKER",
            circuit_reason or "Authoritative Bybit daily loss circuit breaker activated",
            level="error",
            metadata={
                "affected_module": "risk",
                "error_code": "DAILY_NET_LOSS_LIMIT_REACHED",
                "authority_source": "bybit_account_transaction_log",
                "trade_net": trade_net,
                "account_net": account_net,
                "fees": authority.get("fees"),
                "loss_limit": loss_limit,
            },
        )
    return enriched


def normalize_execution_block(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("ok"):
        return result
    error = str(result.get("error") or "").strip()
    detail = str(result.get("detail") or "").strip()
    combined = f"{error} {detail}".lower()
    code = error if error in EXPECTED_BLOCK_CODES else None
    if code is None:
        if "symbol already has an active trade" in combined or "already has an exchange position" in combined:
            code = "SYMBOL_ALREADY_ACTIVE"
        elif "active trade limit reached" in combined:
            code = "ACTIVE_TRADE_LIMIT_REACHED"
        elif "dynamic risk capacity exceeded" in combined:
            code = "DYNAMIC_RISK_CAPACITY_EXCEEDED"
        elif "cooldown active until" in combined:
            code = "SYMBOL_REENTRY_COOLDOWN"
        elif "daily net realized loss circuit breaker" in combined or "daily loss circuit breaker" in combined:
            code = "DAILY_LOSS_CIRCUIT_BREAKER"
        elif "risk reward below" in combined or "risk_reward mismatch" in combined:
            code = "RISK_POLICY_REJECTED"
    if code is None:
        return result
    normalized = dict(result)
    normalized["detail"] = detail or error
    normalized["error"] = code
    normalized["execution_blocked"] = True
    return normalized


def enrich_readiness_with_ws(payload: dict[str, Any], ws_status: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    private = dict(ws_status.get("private") or {})
    public = dict(ws_status.get("public") or {})
    rest_ready = bool(result.get("ready_for_execution"))
    private_ready = bool(private.get("connected") and private.get("authenticated"))

    if not rest_ready:
        state = "BLOCKED"
        fallback_mode = "unavailable"
        ready = False
    elif private_ready:
        state = "READY"
        fallback_mode = "private_ws_plus_rest_reconciliation"
        ready = True
    else:
        # Explicit policy: new entries may continue only because accepted order and
        # fill identity are synchronously confirmed through Bybit REST endpoints.
        state = "DEGRADED_REST_FALLBACK"
        fallback_mode = "rest_execution_list_authoritative_fallback"
        ready = True

    degraded_seconds = _degraded_seconds(private)
    result.update(
        execution_readiness_state=state,
        execution_identity_policy=fallback_mode,
        ready_for_execution=ready and bool(result.get("checks", {}).get("admin_auth_configured", True)),
        websocket={
            "private": private,
            "public": public,
            "private_degraded_seconds": degraded_seconds,
            "private_reconnect_count": int(private.get("reconnect_count") or 0),
            "private_last_message_at": private.get("last_message_at"),
            "private_last_error_at": private.get("last_error_at"),
        },
    )
    return result


def persist_private_execution_records(records: list[dict[str, Any]]) -> int:
    persisted = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        exec_id = str(record.get("execId") or "").strip()
        order_id = str(record.get("orderId") or "").strip()
        order_link_id = str(record.get("orderLinkId") or "").strip()
        symbol = str(record.get("symbol") or "").upper().strip()
        if not exec_id or not (order_id or order_link_id):
            continue

        db = SessionLocal()
        try:
            row = _find_trade_for_execution(db, symbol=symbol, order_id=order_id, order_link_id=order_link_id)
            if row is None:
                _safe_bot_event(
                    "PRIVATE_EXECUTION_IDENTITY_UNMATCHED",
                    "Private execution event could not be matched to a Journal row.",
                    level="warning",
                    metadata={"symbol": symbol, "order_id": order_id, "order_link_id": order_link_id, "exec_id": exec_id},
                )
                continue

            metadata = _metadata(row.exchange_metadata)
            evidence = metadata.get("private_execution_evidence")
            evidence_list = list(evidence) if isinstance(evidence, list) else []
            known_ids = {str(item.get("execId") or item.get("exec_id") or "") for item in evidence_list if isinstance(item, dict)}
            if exec_id not in known_ids:
                evidence_list.append(dict(record))
            metadata["private_execution_evidence"] = evidence_list
            metadata["private_execution_identity"] = {
                "exec_id": exec_id,
                "order_id": order_id or row.order_id,
                "order_link_id": order_link_id,
                "fill_qty": record.get("execQty") or record.get("qty"),
                "fill_price": record.get("execPrice") or record.get("price"),
                "fee": record.get("execFee") or record.get("fee"),
                "side": record.get("side"),
                "timestamp": record.get("execTime") or record.get("updatedTime") or record.get("createdTime"),
                "position_idx": record.get("positionIdx"),
                "captured_at": datetime.now(UTC).isoformat(),
                "source": "bybit_private_execution_websocket",
            }
            if order_id and not row.order_id:
                row.order_id = order_id
            row.exchange_metadata = json.dumps(metadata, separators=(",", ":"))
            journal_id = row.journal_id
            db.commit()
            persisted += 1
        except Exception as exc:
            db.rollback()
            _safe_bot_event(
                "PRIVATE_EXECUTION_IDENTITY_PERSIST_FAILED",
                "Private execution identity could not be persisted.",
                level="error",
                metadata={"symbol": symbol, "order_id": order_id, "order_link_id": order_link_id, "exec_id": exec_id, "error": str(exc)},
            )
            continue
        finally:
            db.close()

        try:
            append_trade_event(
                journal_id,
                "PRIVATE_EXECUTION_IDENTITY_PERSISTED",
                "Private Bybit execution identity persisted to the Journal.",
                {"symbol": symbol, "order_id": order_id, "order_link_id": order_link_id, "exec_id": exec_id},
            )
        except Exception:
            pass
    return persisted


def _find_trade_for_execution(db: Any, *, symbol: str, order_id: str, order_link_id: str) -> TradeJournal | None:
    query = db.query(TradeJournal)
    if symbol:
        query = query.filter(TradeJournal.symbol == symbol)
    if order_id:
        row = query.filter(TradeJournal.order_id == order_id).order_by(TradeJournal.id.desc()).first()
        if row is not None:
            return row
    if not order_link_id:
        return None
    for candidate in query.order_by(TradeJournal.id.desc()).limit(100).all():
        metadata = _metadata(candidate.exchange_metadata)
        candidate_link = str(metadata.get("order_link_id") or "").strip()
        if candidate_link == order_link_id:
            return candidate
        order_response = metadata.get("order_response") if isinstance(metadata.get("order_response"), dict) else {}
        if str(order_response.get("orderLinkId") or order_response.get("order_link_id") or "").strip() == order_link_id:
            return candidate
    return None


def _degraded_seconds(private: dict[str, Any]) -> float:
    if private.get("connected") and private.get("authenticated"):
        return 0.0
    raw = private.get("last_error_at") or private.get("connected_at")
    if not raw:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds(), 0.0)


def _metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _safe_bot_event(event_type: str, message: str, *, level: str, metadata: dict[str, Any]) -> None:
    try:
        log_bot_event(event_type, message, level=level, metadata=metadata)
    except Exception:
        pass

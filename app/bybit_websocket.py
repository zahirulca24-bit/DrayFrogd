from __future__ import annotations

import asyncio
import logging
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any, Callable

from app.authoritative_reconciliation import reconcile_state
from app.authoritative_state import get_snapshot, patch_ticker
from app.bot_controls import get_execution_mode
from app.exchange import get_exchange_client
from app.journal import log_bot_event
from app.risk_sync import sync_partial_realized_pnl

logger = logging.getLogger(__name__)
PRIVATE_TOPICS = ("position", "order", "execution", "wallet")
HEALTHCHECK_SECONDS = 5
RECONCILIATION_IDLE_SECONDS = 30
PRIVATE_AUTH_TIMEOUT_SECONDS = 10
CONNECT_TIMEOUT_SECONDS = 10
RETRY_MIN_SECONDS = 2
RETRY_MAX_SECONDS = 30


def _channel_status(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "state": "stopped",
        "connected": False,
        "authenticated": False,
        "topics": [],
        "endpoint": None,
        "connected_at": None,
        "last_message_at": None,
        "last_health_check_at": None,
        "last_error_at": None,
        "next_retry_at": None,
        "connect_attempts": 0,
        "reconnect_count": 0,
        "error": None,
    }


class BybitWebSocketService:
    """Independent Bybit private/public supervisors with REST truth fallback.

    The private and public sockets are supervised separately. A failure in one
    channel never changes the other channel's status. A channel is reported as
    connected only after the underlying pybit socket confirms connectivity;
    the private channel additionally requires pybit's authentication flag.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: dict[str, asyncio.Task] = {}
        self._stop = asyncio.Event()
        self._reconcile = asyncio.Event()
        self._private_ws: Any = None
        self._public_ws: Any = None
        self._private_mode: str | None = None
        self._public_symbols: set[str] = set()
        self._last_reconcile_reason = "startup"
        self._status: dict[str, Any] = {
            "running": False,
            "mode": "demo",
            "private": _channel_status("private"),
            "public": _channel_status("public"),
            "last_private_event": None,
            "last_public_event": None,
            "last_reconciliation": None,
            "last_reconciliation_error": None,
            "private_event_counts": {},
            "public_symbols": [],
        }

    async def start(self) -> None:
        if any(task and not task.done() for task in self._tasks.values()):
            return
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        self._reconcile = asyncio.Event()
        self._set_status(running=True, mode=get_execution_mode())
        self._tasks = {
            "private": asyncio.create_task(
                self._private_supervisor(), name="bybit-private-websocket"
            ),
            "public": asyncio.create_task(
                self._public_supervisor(), name="bybit-public-websocket"
            ),
            "reconcile": asyncio.create_task(
                self._reconciliation_supervisor(),
                name="bybit-websocket-reconciliation",
            ),
        }

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks.values():
            task.cancel()
        for task in self._tasks.values():
            try:
                await task
            except asyncio.CancelledError:
                pass
        await asyncio.to_thread(self._close_private_client)
        await asyncio.to_thread(self._close_public_client)
        self._tasks = {}
        self._set_channel(
            "private",
            connected=False,
            authenticated=False,
            state="stopped",
            next_retry_at=None,
        )
        self._set_channel(
            "public",
            connected=False,
            authenticated=False,
            state="stopped",
            next_retry_at=None,
        )
        self._set_status(running=False)

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            status = deepcopy(self._status)
        status["authoritative_snapshot"] = {
            key: value for key, value in get_snapshot().items() if key != "trades"
        }
        return status

    def request_reconciliation(self, reason: str) -> None:
        self._last_reconcile_reason = reason
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._reconcile.set)

    async def _private_supervisor(self) -> None:
        retry_seconds = RETRY_MIN_SECONDS
        while not self._stop.is_set():
            mode = get_execution_mode()
            self._set_status(mode=mode)
            client = get_exchange_client(mode)
            if not client.has_credentials():
                await asyncio.to_thread(self._close_private_client)
                self._set_channel(
                    "private",
                    connected=False,
                    authenticated=False,
                    state="credentials_missing",
                    error="Bybit API credentials are not configured",
                    last_error_at=_utc_now_iso(),
                    next_retry_at=None,
                )
                await self._sleep_or_stop(HEALTHCHECK_SECONDS)
                continue

            try:
                if self._private_ws is None or self._private_mode != mode:
                    await asyncio.to_thread(self._close_private_client)
                    await asyncio.to_thread(
                        self._connect_private_client, mode, client
                    )
                    retry_seconds = RETRY_MIN_SECONDS
                    self.request_reconciliation("private_connected")

                connected = _socket_is_connected(self._private_ws)
                authenticated = _socket_is_authenticated(self._private_ws)
                if not connected:
                    raise ConnectionError("Private WebSocket socket is disconnected")
                if not authenticated:
                    raise PermissionError(
                        "Private WebSocket authentication is not confirmed"
                    )

                self._set_channel(
                    "private",
                    connected=True,
                    authenticated=True,
                    state="connected",
                    endpoint=getattr(self._private_ws, "endpoint", None),
                    last_health_check_at=_utc_now_iso(),
                    next_retry_at=None,
                    error=None,
                )
                await self._sleep_or_stop(HEALTHCHECK_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = _format_error(exc)
                self._record_channel_failure("private", error, retry_seconds)
                _safe_bot_event(
                    "bybit_private_websocket_error",
                    error,
                    {"mode": mode, "retry_seconds": retry_seconds},
                    level="warning",
                )
                await asyncio.to_thread(self._close_private_client)
                await self._sleep_or_stop(retry_seconds)
                retry_seconds = min(retry_seconds * 2, RETRY_MAX_SECONDS)

    async def _public_supervisor(self) -> None:
        retry_seconds = RETRY_MIN_SECONDS
        while not self._stop.is_set():
            desired = _desired_public_symbols()
            try:
                if self._public_ws is None or desired != self._public_symbols:
                    await asyncio.to_thread(self._close_public_client)
                    await asyncio.to_thread(self._connect_public_client, desired)
                    retry_seconds = RETRY_MIN_SECONDS

                if not _socket_is_connected(self._public_ws):
                    raise ConnectionError("Public WebSocket socket is disconnected")

                self._set_channel(
                    "public",
                    connected=True,
                    authenticated=False,
                    state="connected",
                    endpoint=getattr(self._public_ws, "endpoint", None),
                    last_health_check_at=_utc_now_iso(),
                    next_retry_at=None,
                    error=None,
                )
                await self._sleep_or_stop(HEALTHCHECK_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = _format_error(exc)
                self._record_channel_failure("public", error, retry_seconds)
                _safe_bot_event(
                    "bybit_public_websocket_error",
                    error,
                    {"symbols": sorted(desired), "retry_seconds": retry_seconds},
                    level="warning",
                )
                await asyncio.to_thread(self._close_public_client)
                await self._sleep_or_stop(retry_seconds)
                retry_seconds = min(retry_seconds * 2, RETRY_MAX_SECONDS)

    async def _reconciliation_supervisor(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._reconcile.wait(), timeout=RECONCILIATION_IDLE_SECONDS
                )
            except TimeoutError:
                continue
            self._reconcile.clear()
            await asyncio.sleep(0.25)
            reason = self._last_reconcile_reason
            mode = get_execution_mode()
            try:
                client = get_exchange_client(mode)
                result = await asyncio.to_thread(
                    reconcile_state,
                    client,
                    source=f"bybit_websocket:{reason}",
                )
                if "execution" in reason:
                    await asyncio.to_thread(sync_partial_realized_pnl, client)
                if result.get("ok"):
                    self._set_status(
                        last_reconciliation={
                            "at": _utc_now_iso(),
                            "reason": reason,
                            "active_positions": len(
                                result.get("authoritative_trades") or []
                            ),
                        },
                        last_reconciliation_error=None,
                    )
                else:
                    self._set_status(
                        last_reconciliation_error=result.get("error")
                        or "Reconciliation failed"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = _format_error(exc)
                logger.exception("WebSocket-triggered reconciliation failed")
                self._set_status(last_reconciliation_error=error)

    def _connect_private_client(self, mode: str, client: Any) -> None:
        self._increment_connect_attempt("private")
        self._set_channel(
            "private",
            connected=False,
            authenticated=False,
            state="connecting",
            error=None,
            next_retry_at=None,
        )
        WebSocket = _pybit_websocket_class()
        ws = WebSocket(
            testnet=False,
            demo=mode == "demo",
            channel_type="private",
            api_key=client.api_key,
            api_secret=client.api_secret,
            retries=3,
            restart_on_error=False,
        )
        if not _wait_until(
            lambda: _socket_is_connected(ws), CONNECT_TIMEOUT_SECONDS
        ):
            _exit_ws(ws)
            raise TimeoutError(
                "Private WebSocket did not confirm socket connectivity"
            )
        if not _wait_until(
            lambda: _socket_is_authenticated(ws), PRIVATE_AUTH_TIMEOUT_SECONDS
        ):
            endpoint = getattr(ws, "endpoint", "unknown endpoint")
            _exit_ws(ws)
            raise PermissionError(
                f"Private WebSocket authentication was not confirmed for {endpoint}"
            )

        ws.position_stream(self._private_callback)
        ws.order_stream(self._private_callback)
        ws.execution_stream(self._private_callback)
        ws.wallet_stream(self._private_callback)
        self._private_ws = ws
        self._private_mode = mode
        self._set_channel(
            "private",
            connected=True,
            authenticated=True,
            state="connected",
            endpoint=getattr(ws, "endpoint", None),
            connected_at=_utc_now_iso(),
            last_health_check_at=_utc_now_iso(),
            last_error_at=None,
            next_retry_at=None,
            error=None,
            topics=list(PRIVATE_TOPICS),
        )
        _safe_bot_event(
            "bybit_private_websocket_connected",
            f"Bybit {mode} private stream connected and authenticated",
            {"mode": mode, "endpoint": getattr(ws, "endpoint", None)},
        )

    def _connect_public_client(self, desired: set[str]) -> None:
        self._increment_connect_attempt("public")
        self._set_channel(
            "public",
            connected=False,
            authenticated=False,
            state="connecting",
            error=None,
            next_retry_at=None,
        )
        WebSocket = _pybit_websocket_class()
        ws = WebSocket(
            testnet=False,
            channel_type="linear",
            retries=3,
            restart_on_error=False,
        )
        if not _wait_until(
            lambda: _socket_is_connected(ws), CONNECT_TIMEOUT_SECONDS
        ):
            _exit_ws(ws)
            raise TimeoutError("Public WebSocket did not confirm socket connectivity")

        ws.ticker_stream(symbol=sorted(desired), callback=self._public_callback)
        for symbol in sorted(_active_symbols()):
            ws.orderbook_stream(
                depth=1, symbol=symbol, callback=self._public_callback
            )
        self._public_ws = ws
        self._public_symbols = set(desired)
        topics = [f"tickers.{symbol}" for symbol in sorted(desired)]
        topics.extend(
            f"orderbook.1.{symbol}" for symbol in sorted(_active_symbols())
        )
        self._set_channel(
            "public",
            connected=True,
            authenticated=False,
            state="connected",
            endpoint=getattr(ws, "endpoint", None),
            connected_at=_utc_now_iso(),
            last_health_check_at=_utc_now_iso(),
            last_error_at=None,
            next_retry_at=None,
            error=None,
            topics=topics,
        )
        self._set_status(public_symbols=sorted(desired))
        _safe_bot_event(
            "bybit_public_websocket_connected",
            "Bybit public linear stream connected",
            {
                "symbols": sorted(desired),
                "endpoint": getattr(ws, "endpoint", None),
            },
        )

    def _private_callback(self, message: dict[str, Any]) -> None:
        topic = str(message.get("topic") or "private")
        now = _utc_now_iso()
        with self._lock:
            counts = dict(self._status.get("private_event_counts") or {})
            counts[topic] = int(counts.get(topic) or 0) + 1
            self._status["private_event_counts"] = counts
            self._status["last_private_event"] = {
                "topic": topic,
                "at": now,
                "creation_time": message.get("creationTime"),
                "records": len(message.get("data") or []),
            }
        connected = _socket_is_connected(self._private_ws)
        authenticated = _socket_is_authenticated(self._private_ws)
        self._set_channel(
            "private",
            connected=connected,
            authenticated=authenticated,
            state="connected" if connected and authenticated else "reconnecting",
            last_message_at=now,
            error=None if connected and authenticated else "Socket state changed during callback",
        )
        if topic.startswith("execution"):
            self.request_reconciliation("execution")
        elif topic.startswith("position"):
            self.request_reconciliation("position")
        elif topic.startswith("order"):
            self.request_reconciliation("order")
        elif topic.startswith("wallet"):
            self.request_reconciliation("wallet")

    def _public_callback(self, message: dict[str, Any]) -> None:
        topic = str(message.get("topic") or "")
        data = message.get("data")
        if topic.startswith("tickers.") and isinstance(data, dict):
            symbol = str(
                data.get("symbol") or topic.rsplit(".", 1)[-1]
            ).upper()
            patch_ticker(symbol, data)
            event_type = "ticker"
        elif topic.startswith("orderbook."):
            event_type = "orderbook"
        else:
            return
        now = _utc_now_iso()
        connected = _socket_is_connected(self._public_ws)
        self._set_status(
            last_public_event={"topic": topic, "type": event_type, "at": now}
        )
        self._set_channel(
            "public",
            connected=connected,
            state="connected" if connected else "reconnecting",
            last_message_at=now,
            error=None if connected else "Socket state changed during callback",
        )

    def _record_channel_failure(
        self, channel: str, error: str, retry_seconds: int
    ) -> None:
        current = self.get_status().get(channel) or {}
        reconnect_count = int(current.get("reconnect_count") or 0) + 1
        self._set_channel(
            channel,
            connected=False,
            authenticated=False,
            state="reconnecting",
            error=error,
            last_error_at=_utc_now_iso(),
            next_retry_at=_future_iso(retry_seconds),
            reconnect_count=reconnect_count,
        )

    def _increment_connect_attempt(self, channel: str) -> None:
        current = self.get_status().get(channel) or {}
        attempts = int(current.get("connect_attempts") or 0) + 1
        self._set_channel(channel, connect_attempts=attempts)

    async def _sleep_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            pass

    def _close_private_client(self) -> None:
        _exit_ws(self._private_ws)
        self._private_ws = None
        self._private_mode = None

    def _close_public_client(self) -> None:
        _exit_ws(self._public_ws)
        self._public_ws = None
        self._public_symbols = set()

    def _set_channel(self, channel: str, **updates: Any) -> None:
        with self._lock:
            state = dict(self._status.get(channel) or _channel_status(channel))
            state.update(updates)
            self._status[channel] = state

    def _set_status(self, **updates: Any) -> None:
        with self._lock:
            self._status.update(updates)


websocket_service = BybitWebSocketService()


def _pybit_websocket_class() -> Any:
    from pybit.unified_trading import WebSocket

    return WebSocket


def _socket_is_connected(client: Any) -> bool:
    if client is None:
        return False
    checker = getattr(client, "is_connected", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    try:
        return bool(client.ws.sock.connected)
    except (AttributeError, TypeError):
        return False


def _socket_is_authenticated(client: Any) -> bool:
    return bool(client is not None and getattr(client, "auth", False))


def _wait_until(predicate: Callable[[], bool], timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _exit_ws(client: Any) -> None:
    if client is None:
        return
    exit_method = getattr(client, "exit", None)
    if callable(exit_method):
        try:
            exit_method()
        except Exception:
            logger.exception("Failed to close Bybit WebSocket client")


def _active_symbols() -> set[str]:
    return {
        str(trade.get("symbol") or "").upper()
        for trade in get_snapshot().get("trades") or []
        if trade.get("symbol")
    }


def _desired_public_symbols() -> set[str]:
    symbols = _active_symbols()
    try:
        from app.scanner import get_ranked_markets

        symbols.update(
            str(item.get("symbol") or "").upper()
            for item in get_ranked_markets()[:30]
            if item.get("symbol")
        )
    except Exception:
        pass
    return symbols or {"BTCUSDT"}


def _safe_bot_event(
    event_type: str,
    message: str,
    metadata: dict[str, Any],
    *,
    level: str = "info",
) -> None:
    try:
        log_bot_event(event_type, message, level=level, metadata=metadata)
    except Exception:
        logger.exception("Failed to persist WebSocket bot event: %s", event_type)


def _format_error(exc: Exception) -> str:
    message = str(exc).strip() or "No error message"
    return f"{type(exc).__name__}: {message}"


def _future_iso(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()

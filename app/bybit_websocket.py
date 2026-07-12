from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from app.authoritative_state import get_snapshot, patch_ticker
from app.bot_controls import get_execution_mode
from app.exchange import get_exchange_client
from app.journal import log_bot_event
from app.reconciliation import reconcile_state
from app.risk_sync import sync_partial_realized_pnl

logger = logging.getLogger(__name__)
PRIVATE_TOPICS = ("position", "order", "execution", "wallet")
PUBLIC_REFRESH_SECONDS = 10



def _channel_status(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "state": "stopped",
        "connected": False,
        "authenticated": False,
        "topics": [],
        "connected_at": None,
        "last_message_at": None,
        "error": None,
    }

class BybitWebSocketService:
    """Bybit V5 private/public stream supervisor with REST reconciliation fallback.

    The official ``pybit`` client owns socket authentication, heartbeat and
    reconnect behavior. Stream callbacks never become the accounting authority:
    they request a debounced REST reconciliation, while public ticker updates
    only patch mark-price fields on the last authoritative snapshot.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._reconcile = asyncio.Event()
        self._private_ws: Any = None
        self._public_ws: Any = None
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
        if self._task and not self._task.done():
            return
        self._loop = asyncio.get_running_loop()
        self._stop.clear()
        self._set_status(running=True, mode=get_execution_mode())
        self._task = asyncio.create_task(self._supervisor(), name="bybit-websocket-supervisor")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await asyncio.to_thread(self._close_clients)
        self._task = None
        self._set_channel("private", connected=False, authenticated=False, state="stopped")
        self._set_channel("public", connected=False, state="stopped")
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
        if self._loop:
            self._loop.call_soon_threadsafe(self._reconcile.set)

    async def _supervisor(self) -> None:
        while not self._stop.is_set():
            mode = get_execution_mode()
            try:
                await asyncio.to_thread(self._ensure_clients, mode)
                await self._run_pending_reconciliation(mode)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive network guard
                logger.exception("Bybit WebSocket supervisor failed")
                self._set_status(last_reconciliation_error=str(exc))
                self._set_channel("private", connected=False, authenticated=False, state="reconnecting", error=str(exc))
                self._set_channel("public", connected=False, state="reconnecting", error=str(exc))
                await asyncio.to_thread(self._close_clients)
            try:
                await asyncio.wait_for(self._reconcile.wait(), timeout=PUBLIC_REFRESH_SECONDS)
            except TimeoutError:
                pass

    async def _run_pending_reconciliation(self, mode: str) -> None:
        if not self._reconcile.is_set():
            return
        self._reconcile.clear()
        await asyncio.sleep(0.25)
        reason = self._last_reconcile_reason
        client = get_exchange_client(mode)
        result = await asyncio.to_thread(reconcile_state, client, source=f"bybit_websocket:{reason}")
        if "execution" in reason:
            await asyncio.to_thread(sync_partial_realized_pnl, client)
        if result.get("ok"):
            self._set_status(
                last_reconciliation={
                    "at": _utc_now_iso(),
                    "reason": reason,
                    "active_positions": len(result.get("authoritative_trades") or []),
                },
                last_reconciliation_error=None,
            )
        else:
            self._set_status(last_reconciliation_error=result.get("error") or "Reconciliation failed")

    def _ensure_clients(self, mode: str) -> None:
        client = get_exchange_client(mode)
        self._set_status(mode=mode)
        if not client.has_credentials():
            self._set_channel(
                "private",
                connected=False,
                authenticated=False,
                state="credentials_missing",
                error="Bybit API credentials are not configured",
            )
        elif self._private_ws is None:
            WebSocket = _pybit_websocket_class()
            self._private_ws = WebSocket(
                testnet=False,
                demo=mode == "demo",
                channel_type="private",
                api_key=client.api_key,
                api_secret=client.api_secret,
            )
            self._private_ws.position_stream(self._private_callback)
            self._private_ws.order_stream(self._private_callback)
            self._private_ws.execution_stream(self._private_callback)
            self._private_ws.wallet_stream(self._private_callback)
            self._set_channel(
                "private",
                connected=True,
                authenticated=True,
                state="connected",
                connected_at=_utc_now_iso(),
                error=None,
                topics=list(PRIVATE_TOPICS),
            )
            _safe_bot_event("bybit_private_websocket_connected", f"Bybit {mode} private stream connected", {"mode": mode})
            self.request_reconciliation("private_connected")

        desired = _desired_public_symbols()
        if self._public_ws is None or desired != self._public_symbols:
            if self._public_ws is not None:
                _exit_ws(self._public_ws)
            WebSocket = _pybit_websocket_class()
            self._public_ws = WebSocket(testnet=False, channel_type="linear")
            self._public_ws.ticker_stream(symbol=sorted(desired), callback=self._public_callback)
            for symbol in sorted(_active_symbols()):
                self._public_ws.orderbook_stream(depth=1, symbol=symbol, callback=self._public_callback)
            self._public_symbols = desired
            self._set_channel(
                "public",
                connected=True,
                authenticated=False,
                state="connected",
                connected_at=_utc_now_iso(),
                error=None,
                topics=[f"tickers.{symbol}" for symbol in sorted(desired)],
            )
            self._set_status(public_symbols=sorted(desired))
            _safe_bot_event("bybit_public_websocket_connected", "Bybit public linear stream connected", {"symbols": sorted(desired)})

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
            symbol = str(data.get("symbol") or topic.rsplit(".", 1)[-1]).upper()
            patch_ticker(symbol, data)
            event_type = "ticker"
        elif topic.startswith("orderbook."):
            event_type = "orderbook"
        else:
            return
        self._set_status(last_public_event={"topic": topic, "type": event_type, "at": _utc_now_iso()})

    def _close_clients(self) -> None:
        _exit_ws(self._private_ws)
        _exit_ws(self._public_ws)
        self._private_ws = None
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


def _safe_bot_event(event_type: str, message: str, metadata: dict[str, Any]) -> None:
    try:
        log_bot_event(event_type, message, metadata=metadata)
    except Exception:
        logger.exception("Failed to persist WebSocket bot event: %s", event_type)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()

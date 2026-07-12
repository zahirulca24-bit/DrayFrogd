from __future__ import annotations

from threading import RLock
from typing import Any

from app.authoritative_state import get_snapshot, publish_snapshot
from app.close_fill_sync import fetch_exact_close_result
from app.execution import close_trade, get_active_trades, replace_active_trades
from app.exchange import BybitClient
from app.reconciliation_helpers import (
    _candidate_id, _dedupe_candidates, _match_candidate, _merge_position,
    _pending_order_trade, _recover_exchange_position, _safe_open_trade_history,
)
from app.reconciliation_identity import (
    _orders_by_identity, _orders_by_symbol, _position_identity, _position_is_open,
    _ticker_price_map, _trade_identity,
)
from app.reconciliation_persistence import (
    _mark_journal_stale, _persist_active_trade, _persist_pending_close_sync,
    _persist_reconciliation_event, _persist_reconciliation_state,
)
from app.risk import release_active_trade
from app.trade_state import is_capacity_blocking_status

_reconciliation_lock = RLock()


def reconcile_state(client: BybitClient, *, source: str = "rest_reconciliation") -> dict[str, Any]:
    with _reconciliation_lock:
        return _reconcile_state_locked(client, source=source)


def _reconcile_state_locked(client: BybitClient, *, source: str = "rest_reconciliation") -> dict[str, Any]:
    """Build one exchange-authoritative position snapshot."""

    mode = str(getattr(client, "mode", "demo") or "demo").lower()
    local_trades = get_active_trades()
    journal_trades = _safe_open_trade_history()
    candidates = _dedupe_candidates([*local_trades, *journal_trades])

    ok_orders, open_orders, orders_error = client.safe_fetch_open_orders()
    ok_positions, positions, positions_error = client.safe_fetch_positions()
    ok_tickers, tickers, _ = client.safe_fetch_market_tickers()
    if not ok_orders or not ok_positions:
        errors = [item for item in [orders_error, positions_error] if item]
        previous_snapshot = get_snapshot()
        publish_snapshot(
            list(previous_snapshot.get("trades") or []),
            mode=mode,
            source=f"{source}:error_preserved_previous",
            positions_synced=False,
            errors=errors or ["Reconciliation failed"],
        )
        return {
            "ok": False,
            "error": orders_error or positions_error or "Reconciliation failed",
            "trades": local_trades,
            "authoritative_trades": [],
        }

    open_orders_by_id = {
        str(order.get("orderId")): order
        for order in open_orders
        if order.get("orderId")
    }
    open_orders_by_identity = _orders_by_identity(open_orders, mode)
    open_orders_by_symbol = _orders_by_symbol(open_orders)
    open_positions = [position for position in positions if _position_is_open(position)]
    ticker_prices = _ticker_price_map(tickers if ok_tickers else [])

    authoritative_trades: list[dict[str, Any]] = []
    safety_trades: list[dict[str, Any]] = []
    closed_trades: list[dict[str, Any]] = []
    closed_symbols: list[str] = []
    updates: list[dict[str, Any]] = []
    matched_candidate_ids: set[str] = set()

    for position in open_positions:
        identity = _position_identity(position, mode)
        candidate = _match_candidate(candidates, identity)
        recovered = False
        if candidate is None:
            candidate = _recover_exchange_position(position, mode)
            candidates.append(candidate)
            recovered = True

        candidate_id = _candidate_id(candidate)
        if candidate_id:
            matched_candidate_ids.add(candidate_id)

        reconciled = _merge_position(
            candidate,
            position,
            open_orders_by_symbol.get(identity[1], []),
            ticker_prices.get(identity[1]),
            identity,
            recovered=recovered,
        )
        authoritative_trades.append(reconciled)
        safety_trades.append(reconciled)
        updates.append(
            {
                "symbol": reconciled.get("symbol"),
                "direction": reconciled.get("direction"),
                "position_idx": identity[3],
                "status": reconciled.get("status"),
                "reason": "Exchange-confirmed position synchronized",
                "recovered": recovered,
            }
        )
        _persist_active_trade(reconciled, candidate)

    for trade in candidates:
        candidate_id = _candidate_id(trade)
        if candidate_id and candidate_id in matched_candidate_ids:
            continue

        symbol = str(trade.get("symbol") or "").upper().strip()
        journal_id = str(trade.get("journal_id") or "").strip()
        order_id = str(trade.get("order_id") or "").strip()
        status = str(trade.get("status") or "").lower()
        identity = _trade_identity(trade, mode)
        open_order = open_orders_by_id.get(order_id) if order_id else None
        if open_order is None:
            identity_orders = open_orders_by_identity.get(identity, [])
            open_order = identity_orders[0] if identity_orders else None

        if open_order is not None and is_capacity_blocking_status(status):
            pending = _pending_order_trade(trade, open_order)
            safety_trades.append(pending)
            updates.append(
                {
                    "symbol": symbol,
                    "status": pending.get("status"),
                    "reason": "Open order exists; exchange position is pending",
                }
            )
            _persist_reconciliation_state(
                journal_id,
                pending,
                event_type="RECONCILIATION_PENDING_ORDER",
                message="Open order exists but no exchange position is confirmed yet.",
            )
            continue

        if not is_capacity_blocking_status(status) and status not in {"close_pending_sync", "journal_stale"}:
            continue

        exact_close, close_sync_error = fetch_exact_close_result(client, trade)
        if exact_close is not None:
            closed_trade = close_trade(journal_id, exact_close) if journal_id else None
            if closed_trade is None:
                closed_trade = {**trade, **exact_close, "status": "closed"}
            closed_symbols.append(symbol)
            closed_trades.append(closed_trade)
            updates.append(
                {
                    "symbol": symbol,
                    "status": "closed",
                    "reason": "Exact Bybit closed PnL synchronized",
                }
            )
            _persist_reconciliation_event(
                journal_id,
                "RECONCILED_CLOSED_EXACT",
                "Exchange position is absent and exact Bybit close fill/PnL/fees were synchronized.",
                exact_close,
            )
            continue

        stale = _mark_journal_stale(
            trade,
            error=close_sync_error or "Exchange position and open order are absent; exact close data is not available yet",
        )
        updates.append(
            {
                "symbol": symbol,
                "status": stale["status"],
                "reason": stale["close_sync_error"],
            }
        )
        _persist_pending_close_sync(journal_id, stale)

    replace_active_trades(_dedupe_candidates(safety_trades))
    for symbol in closed_symbols:
        release_active_trade(symbol)

    snapshot = publish_snapshot(
        authoritative_trades,
        mode=mode,
        source=source,
        positions_synced=True,
        errors=[],
    )

    return {
        "ok": True,
        "trades": _dedupe_candidates(safety_trades),
        "authoritative_trades": authoritative_trades,
        "closed_trades": closed_trades,
        "closed": closed_symbols,
        "updates": updates,
        "snapshot": snapshot,
    }

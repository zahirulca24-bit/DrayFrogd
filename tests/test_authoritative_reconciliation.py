from __future__ import annotations

from unittest.mock import patch

from app.authoritative_state import get_snapshot, reset_snapshot
from app.authoritative_reconciliation import reconcile_state
from app.database import Base, engine
Base.metadata.create_all(bind=engine)


class FakeClient:
    mode = "demo"

    def __init__(self, positions: list[dict], orders: list[dict] | None = None) -> None:
        self.positions = positions
        self.orders = orders or []

    def safe_fetch_open_orders(self):
        return True, list(self.orders), None

    def safe_fetch_positions(self):
        return True, list(self.positions), None

    def safe_fetch_market_tickers(self):
        return True, [{"symbol": "LABUSDT", "markPrice": "0.45", "lastPrice": "0.45"}], None


def position(side: str = "Sell", position_idx: int = 0) -> dict:
    return {
        "category": "linear",
        "symbol": "LABUSDT",
        "side": side,
        "size": "100",
        "positionIdx": position_idx,
        "avgPrice": "0.44",
        "markPrice": "0.45",
        "leverage": "10",
        "positionValue": "45",
        "positionIM": "4.5",
        "unrealisedPnl": "-1",
        "stopLoss": "0.46",
        "takeProfit": "0.40",
        "createdTime": "1783900000000",
    }


def recovered_payload(trade: dict) -> dict:
    return {**trade, "journal_id": trade.get("journal_id") or "exchange-recovered"}


def test_exchange_only_position_is_recovered_once_and_published() -> None:
    reset_snapshot()
    client = FakeClient([position()])

    with (
        patch("app.authoritative_reconciliation.get_active_trades", return_value=[]),
        patch("app.authoritative_reconciliation._safe_open_trade_history", return_value=[]),
        patch("app.reconciliation_helpers.get_trade_by_execution_key", return_value=None),
        patch("app.reconciliation_helpers.create_trade_entry", side_effect=recovered_payload) as create_mock,
        patch("app.reconciliation_persistence.update_trade_entry"),
        patch("app.reconciliation_persistence.append_trade_event"),
        patch("app.authoritative_reconciliation.replace_active_trades") as replace_mock,
    ):
        result = reconcile_state(client, source="test")

    assert result["ok"] is True
    assert len(result["authoritative_trades"]) == 1
    trade = result["authoritative_trades"][0]
    assert trade["symbol"] == "LABUSDT"
    assert trade["direction"] == "short"
    assert trade["exchange_confirmed_active"] is True
    assert trade["position_synced"] is True
    assert trade["status"] == "active"
    assert create_mock.call_count == 1
    replace_mock.assert_called_once()
    snapshot = get_snapshot()
    assert snapshot["positions_synced"] is True
    assert len(snapshot["trades"]) == 1


def test_matching_exchange_position_reuses_existing_journal_metadata() -> None:
    reset_snapshot()
    existing = {
        "journal_id": "jrnl-1",
        "execution_key": "exec-1",
        "symbol": "LABUSDT",
        "direction": "short",
        "execution_mode": "demo",
        "strategy_name": "ema_pullback",
        "strategy": "ema_pullback",
        "entry": 0.44,
        "stop_loss": 0.46,
        "take_profit": 0.40,
        "quantity": 100,
        "status": "active",
        "opened_at": "2026-07-13T00:00:00+00:00",
        "exchange_metadata": {},
    }
    client = FakeClient([position()])

    with (
        patch("app.authoritative_reconciliation.get_active_trades", return_value=[existing]),
        patch("app.authoritative_reconciliation._safe_open_trade_history", return_value=[existing]),
        patch("app.reconciliation_helpers.create_trade_entry") as create_mock,
        patch("app.reconciliation_persistence.update_trade_entry"),
        patch("app.reconciliation_persistence.append_trade_event"),
        patch("app.authoritative_reconciliation.replace_active_trades"),
    ):
        result = reconcile_state(client)

    assert result["authoritative_trades"][0]["journal_id"] == "jrnl-1"
    assert result["authoritative_trades"][0]["strategy_name"] == "ema_pullback"
    create_mock.assert_not_called()


def test_journal_only_row_is_not_operator_active() -> None:
    reset_snapshot()
    from datetime import UTC, datetime, timedelta
    past_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    stale = {
        "journal_id": "jrnl-stale",
        "symbol": "LABUSDT",
        "direction": "short",
        "execution_mode": "demo",
        "entry": 0.44,
        "stop_loss": 0.46,
        "take_profit": 0.40,
        "quantity": 100,
        "status": "close_pending_sync",
        "exchange_metadata": {
            "close_pending_since": past_time
        },
    }
    client = FakeClient([])

    with (
        patch("app.authoritative_reconciliation.get_active_trades", return_value=[stale]),
        patch("app.authoritative_reconciliation._safe_open_trade_history", return_value=[stale]),
        patch("app.authoritative_reconciliation.fetch_exact_close_result", return_value=(None, "not available yet")),
        patch("app.authoritative_reconciliation.update_trade_entry") as update_mock,
        patch("app.authoritative_reconciliation.append_trade_event"),
        patch("app.authoritative_reconciliation.replace_active_trades") as replace_mock,
    ):
        result = reconcile_state(client)

    assert result["ok"] is True
    assert result["authoritative_trades"] == []
    assert result["trades"] == []
    assert update_mock.call_args.kwargs == {}
    persisted = update_mock.call_args.args[1]
    assert persisted["status"] == "closed"
    assert persisted["exchange_metadata"]["close_pnl_is_estimate"] is True
    assert get_snapshot()["trades"] == []
    update_mock.assert_called_once()
    replace_mock.assert_called_once()


def test_journal_only_row_is_marked_pending_sync_within_window() -> None:
    reset_snapshot()
    active_stale = {
        "journal_id": "jrnl-active-stale",
        "symbol": "LABUSDT",
        "direction": "short",
        "execution_mode": "demo",
        "entry": 0.44,
        "stop_loss": 0.46,
        "take_profit": 0.40,
        "quantity": 100,
        "status": "active",
        "exchange_metadata": {},
    }
    client = FakeClient([])

    with (
        patch("app.authoritative_reconciliation.get_active_trades", return_value=[active_stale]),
        patch("app.authoritative_reconciliation._safe_open_trade_history", return_value=[active_stale]),
        patch("app.authoritative_reconciliation.fetch_exact_close_result", return_value=(None, "not available yet")),
        patch("app.reconciliation_persistence.update_trade_entry") as update_mock,
        patch("app.reconciliation_persistence.append_trade_event"),
        patch("app.authoritative_reconciliation.replace_active_trades") as replace_mock,
    ):
        result = reconcile_state(client)

    assert result["ok"] is True
    assert result["authoritative_trades"] == []
    assert result["trades"] == []
    assert update_mock.call_args.kwargs == {}
    persisted = update_mock.call_args.args[1]
    assert persisted["status"] == "close_pending_sync"
    assert persisted["result"] == "reconciliation_stale"


def test_opposite_side_same_symbol_is_not_merged() -> None:
    reset_snapshot()
    long_trade = {
        "journal_id": "jrnl-long",
        "symbol": "LABUSDT",
        "direction": "long",
        "execution_mode": "demo",
        "entry": 0.44,
        "stop_loss": 0.42,
        "take_profit": 0.48,
        "quantity": 100,
        "status": "active",
        "exchange_metadata": {},
    }
    client = FakeClient([position(side="Sell", position_idx=2)])

    with (
        patch("app.authoritative_reconciliation.get_active_trades", return_value=[long_trade]),
        patch("app.authoritative_reconciliation._safe_open_trade_history", return_value=[long_trade]),
        patch("app.reconciliation_helpers.get_trade_by_execution_key", return_value=None),
        patch("app.reconciliation_helpers.create_trade_entry", side_effect=recovered_payload) as create_mock,
        patch("app.authoritative_reconciliation.fetch_exact_close_result", return_value=(None, "not available yet")),
        patch("app.reconciliation_persistence.update_trade_entry"),
        patch("app.reconciliation_persistence.append_trade_event"),
        patch("app.authoritative_reconciliation.replace_active_trades"),
    ):
        result = reconcile_state(client)

    assert len(result["authoritative_trades"]) == 1
    assert result["authoritative_trades"][0]["direction"] == "short"
    assert create_mock.call_count == 1


def test_transient_exchange_failure_preserves_previous_snapshot() -> None:
    reset_snapshot()
    from app.authoritative_state import publish_snapshot

    publish_snapshot(
        [{"journal_id": "jrnl-1", "symbol": "LABUSDT", "status": "active"}],
        mode="demo",
        source="previous",
        positions_synced=True,
    )

    class FailingClient(FakeClient):
        def safe_fetch_open_orders(self):
            return False, [], "temporary orders failure"

        def safe_fetch_positions(self):
            return False, [], "temporary positions failure"

    with (
        patch("app.authoritative_reconciliation.get_active_trades", return_value=[]),
        patch("app.authoritative_reconciliation._safe_open_trade_history", return_value=[]),
    ):
        result = reconcile_state(FailingClient([]), source="test_failure")

    assert result["ok"] is False
    snapshot = get_snapshot()
    assert snapshot["positions_synced"] is False
    assert snapshot["trades"][0]["symbol"] == "LABUSDT"
    assert "error_preserved_previous" in snapshot["source"]


def test_absent_position_uses_exact_close_before_marking_stale() -> None:
    reset_snapshot()
    trade = {
        "journal_id": "jrnl-close",
        "symbol": "LABUSDT",
        "direction": "short",
        "execution_mode": "demo",
        "entry": 0.44,
        "stop_loss": 0.46,
        "take_profit": 0.40,
        "quantity": 100,
        "status": "active",
        "exchange_metadata": {},
    }
    exact = {
        "status": "closed",
        "exit_price": 0.42,
        "realized_pnl": 2.0,
        "fees": 0.1,
        "result": "profit",
        "close_reason": "exchange_closed_pnl",
    }
    client = FakeClient([])

    with (
        patch("app.authoritative_reconciliation.get_active_trades", return_value=[trade]),
        patch("app.authoritative_reconciliation._safe_open_trade_history", return_value=[trade]),
        patch("app.authoritative_reconciliation.fetch_exact_close_result", return_value=(exact, None)),
        patch("app.authoritative_reconciliation.close_trade", return_value={**trade, **exact}) as close_mock,
        patch("app.authoritative_reconciliation.replace_active_trades"),
        patch("app.authoritative_reconciliation.release_active_trade") as release_mock,
        patch("app.reconciliation_persistence.update_trade_entry"),
        patch("app.reconciliation_persistence.append_trade_event"),
    ):
        result = reconcile_state(client)

    assert result["ok"] is True
    assert result["authoritative_trades"] == []
    assert result["closed"] == ["LABUSDT"]
    close_mock.assert_called_once_with("jrnl-close", exact)
    release_mock.assert_called_once_with("LABUSDT")

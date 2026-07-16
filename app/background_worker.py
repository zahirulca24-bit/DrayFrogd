from __future__ import annotations

import asyncio
import logging

from app.authoritative_reconciliation import reconcile_state
from app.bot_controls import can_execute, get_execution_mode
from app.bybit_websocket import websocket_service
from app.close_fill_sync import repair_incomplete_journal_closes
from app.config import settings
from app.exchange import get_exchange_client
from app.exchange_journal_backfill import backfill_exchange_journal_lifecycle
from app.intraday_protection_guard import enforce_intraday_protection
from app.journal import log_bot_event
from app.native_profit_reconcile import reconcile_native_profit_orders
from app.risk import extract_account_equity, refresh_risk_state
from app.risk_cooldown_sync import sync_loss_cooldowns
from app.risk_execution import execute_signal
from app.risk_sync import sync_partial_realized_pnl
from app.runtime_integration import install_runtime_integration
from app.runtime_watchdog import run_watchdog_cycle
from app.scalping_profit_lock_guard import enforce_scalping_tp2_profit_locks
from app.scanner import get_active_signals, run_scan
from app.trade_management import manage_open_trades


logger = logging.getLogger(__name__)
NATIVE_TP_MONITOR_SECONDS = 2
EXPECTED_EXECUTION_BLOCKS = {
    "DUPLICATE_EXECUTION",
    "SYMBOL_ALREADY_ACTIVE",
    "ACTIVE_TRADE_LIMIT_REACHED",
    "DYNAMIC_RISK_CAPACITY_EXCEEDED",
    "DAILY_TRADE_LIMIT_REACHED",
    "SYMBOL_REENTRY_COOLDOWN",
}


def _safe_log_bot_event(event_type: str, message: str, *, level: str = "info", metadata: dict | None = None) -> None:
    try:
        log_bot_event(event_type, message, level=level, metadata=metadata)
    except Exception:
        logger.exception("Failed to persist bot event: %s", event_type)


def _is_expected_execution_block(value: object) -> bool:
    return str(value or "").strip() in EXPECTED_EXECUTION_BLOCKS


async def native_profit_monitor_loop() -> None:
    """Reconcile native fills and verify protection independently of scan cadence."""

    while True:
        try:
            client = get_exchange_client(get_execution_mode())
            result = await asyncio.to_thread(reconcile_native_profit_orders, client)
            if not result.get("ok") and result.get("errors"):
                logger.debug("Native TP reconciliation pending: %s", result.get("errors"))

            scalping_result = await asyncio.to_thread(enforce_scalping_tp2_profit_locks, client)
            if not scalping_result.get("ok") and scalping_result.get("errors"):
                logger.debug("Scalping TP2 profit-lock verification pending: %s", scalping_result.get("errors"))

            protection_result = await asyncio.to_thread(enforce_intraday_protection, client)
            if not protection_result.get("ok") and protection_result.get("errors"):
                logger.debug("Intraday protection verification pending: %s", protection_result.get("errors"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive watcher guard
            logger.exception("Native TP monitor crashed")
            _safe_log_bot_event(
                "native_tp_monitor_error",
                str(exc),
                level="error",
                metadata={
                    "endpoint": "background:native_tp_monitor",
                    "affected_module": "trade_management",
                    "error_code": "NATIVE_TP_MONITOR_ERROR",
                    "error": str(exc),
                },
            )
        await asyncio.sleep(NATIVE_TP_MONITOR_SECONDS)


async def auto_trading_loop() -> None:
    install_runtime_integration()
    await websocket_service.start()
    native_monitor = asyncio.create_task(native_profit_monitor_loop())
    try:
        while True:
            try:
                client = get_exchange_client(get_execution_mode())
                reconciliation_result = await asyncio.to_thread(reconcile_state, client)
                if not reconciliation_result.get("ok"):
                    _safe_log_bot_event(
                        "reconciliation_failed",
                        reconciliation_result.get("error", "Reconciliation failed"),
                        level="warning",
                        metadata={
                            "endpoint": "background:reconciliation",
                            "affected_module": "reconciliation",
                            "error_code": "RECONCILIATION_FAILED",
                            "retry_count": 1,
                            "result": reconciliation_result,
                        },
                    )

                management_result = await asyncio.to_thread(manage_open_trades, client)
                if not management_result.get("ok"):
                    _safe_log_bot_event(
                        "trade_management_failed",
                        management_result.get("error", "Trade management failed"),
                        level="warning",
                        metadata={
                            "endpoint": "background:trade_management",
                            "affected_module": "trade_management",
                            "error_code": "TRADE_MANAGEMENT_FAILED",
                            "retry_count": 1,
                            "result": management_result,
                        },
                    )

                partial_pnl_result = await asyncio.to_thread(sync_partial_realized_pnl, client)
                if not partial_pnl_result.get("ok") and partial_pnl_result.get("errors"):
                    logger.debug("Partial realized PnL sync pending: %s", partial_pnl_result.get("errors"))

                ledger_repair_result = await asyncio.to_thread(repair_incomplete_journal_closes, client)
                if not ledger_repair_result.get("ok") and ledger_repair_result.get("pending"):
                    logger.debug("Ledger close repair pending: %s", ledger_repair_result.get("pending"))

                lifecycle_result = await asyncio.to_thread(backfill_exchange_journal_lifecycle, client)
                if not lifecycle_result.get("ok"):
                    _safe_log_bot_event(
                        "exchange_journal_backfill_failed",
                        lifecycle_result.get("error") or "Exchange lifecycle backfill failed",
                        level="warning",
                        metadata={
                            "endpoint": "background:exchange_journal_backfill",
                            "affected_module": "journal",
                            "error_code": "EXCHANGE_JOURNAL_BACKFILL_FAILED",
                            "result": lifecycle_result,
                        },
                    )
                elif lifecycle_result.get("pending"):
                    logger.debug("Exchange journal lifecycle backfill pending: %s", lifecycle_result.get("pending"))

                await asyncio.to_thread(sync_loss_cooldowns)

                wallet_ok, wallet, wallet_error = await asyncio.to_thread(client.safe_fetch_wallet_balance)
                account_equity = extract_account_equity(wallet) if wallet_ok else None
                risk_state = await asyncio.to_thread(refresh_risk_state, account_equity)
                if not wallet_ok and risk_state.get("day_start_equity") is None:
                    _safe_log_bot_event(
                        "risk_equity_unavailable",
                        wallet_error or "Day-start equity is unavailable",
                        level="warning",
                        metadata={
                            "endpoint": "background:risk_refresh",
                            "affected_module": "risk",
                            "error_code": "RISK_EQUITY_UNAVAILABLE",
                        },
                    )

                watchdog_result = await asyncio.to_thread(
                    run_watchdog_cycle, client, reconciliation_result=reconciliation_result
                )
                if watchdog_result.get("execution_blocked"):
                    logger.warning("Runtime watchdog blocked new execution: %s", watchdog_result.get("reasons"))

                allowed, reason = can_execute()
                if not allowed:
                    if reason:
                        logger.debug("Auto trading blocked: %s", reason)
                    await asyncio.sleep(settings.bot_scan_interval_seconds)
                    continue

                result = await asyncio.to_thread(run_scan, client)
                if not result.get("ok"):
                    _safe_log_bot_event(
                        "scan_failed",
                        result.get("error", "Scanner failed"),
                        level="warning",
                        metadata={
                            **result,
                            "endpoint": "/scanner/results",
                            "affected_module": "scanner",
                            "error_code": "SCAN_FAILED",
                            "retry_count": 1,
                        },
                    )
                    await asyncio.sleep(settings.bot_scan_interval_seconds)
                    continue

                active_signals = result.get("signals") or get_active_signals()
                for signal in active_signals:
                    try:
                        outcome = await asyncio.to_thread(execute_signal, client, signal, True)
                    except Exception as exc:
                        logger.exception("Auto execution crashed for %s", signal.get("symbol"))
                        _safe_log_bot_event(
                            "auto_execution_error",
                            f"Auto execution crashed for {signal.get('symbol')}",
                            level="error",
                            metadata={
                                "endpoint": "background:auto_execution",
                                "affected_module": "execution",
                                "error_code": "AUTO_EXECUTION_ERROR",
                                "signal": signal,
                                "error": str(exc),
                            },
                        )
                        continue

                    if outcome.get("ok"):
                        _safe_log_bot_event(
                            "trade_executed",
                            f"Executed {signal.get('symbol')} in {get_execution_mode()} mode",
                            metadata={"trade": outcome.get("trade"), "signal": signal},
                        )
                    else:
                        error_message = outcome.get("error", "Unknown execution failure")
                        if _is_expected_execution_block(error_message):
                            logger.debug("Auto execution blocked for %s: %s", signal.get("symbol"), error_message)
                            _safe_log_bot_event(
                                "trade_execution_blocked",
                                f"Execution guard blocked {signal.get('symbol')}",
                                level="info",
                                metadata={
                                    "endpoint": "background:auto_execution",
                                    "affected_module": "execution",
                                    "error_code": str(error_message),
                                    "signal": signal,
                                    "outcome": outcome,
                                },
                            )
                        else:
                            logger.warning("Auto execution failed for %s: %s", signal.get("symbol"), error_message)
                            _safe_log_bot_event(
                                "auto_execution_failed",
                                f"Auto execution failed for {signal.get('symbol')}",
                                level="warning",
                                metadata={
                                    "endpoint": "background:auto_execution",
                                    "affected_module": "execution",
                                    "error_code": "AUTO_EXECUTION_FAILED",
                                    "signal": signal,
                                    "outcome": outcome,
                                    "error": error_message,
                                },
                            )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive background task guard
                logger.exception("Auto trading loop crashed")
                _safe_log_bot_event(
                    "auto_loop_error",
                    str(exc),
                    level="error",
                    metadata={
                        "endpoint": "background:auto_trading_loop",
                        "affected_module": "worker",
                        "error_code": "AUTO_LOOP_ERROR",
                        "retry_count": 1,
                        "error": str(exc),
                    },
                )

            await asyncio.sleep(settings.bot_scan_interval_seconds)
    finally:
        await websocket_service.stop()
        native_monitor.cancel()
        try:
            await native_monitor
        except asyncio.CancelledError:
            pass

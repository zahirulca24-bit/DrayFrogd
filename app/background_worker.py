from __future__ import annotations

import asyncio
import logging

from app.bot_controls import can_execute, get_execution_mode
from app.config import settings
from app.exchange import get_exchange_client
from app.intraday_protection_guard import enforce_intraday_protection
from app.journal import log_bot_event
from app.native_profit_reconcile import reconcile_native_profit_orders
from app.reconciliation import reconcile_state
from app.risk import extract_account_equity, refresh_risk_state
from app.risk_cooldown_sync import sync_loss_cooldowns
from app.risk_execution import execute_signal
from app.risk_sync import sync_partial_realized_pnl
from app.scanner import get_active_signals, run_scan
from app.trade_management import manage_open_trades


logger = logging.getLogger(__name__)
NATIVE_TP_MONITOR_SECONDS = 2


def _safe_log_bot_event(event_type: str, message: str, *, level: str = "info", metadata: dict | None = None) -> None:
    try:
        log_bot_event(event_type, message, level=level, metadata=metadata)
    except Exception:
        logger.exception("Failed to persist bot event: %s", event_type)


async def native_profit_monitor_loop() -> None:
    """Reconcile native fills and verify protection independently of scan cadence."""

    while True:
        try:
            client = get_exchange_client(get_execution_mode())
            result = await asyncio.to_thread(reconcile_native_profit_orders, client)
            if not result.get("ok") and result.get("errors"):
                logger.debug("Native TP reconciliation pending: %s", result.get("errors"))

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

                # Exact negative realized PnL creates a symbol-specific 30-minute
                # cooldown. The expiry is reconstructed from closed_at, so restart
                # and repeated worker cycles cannot bypass or extend it.
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
        native_monitor.cancel()
        try:
            await native_monitor
        except asyncio.CancelledError:
            pass

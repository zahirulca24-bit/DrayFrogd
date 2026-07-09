from __future__ import annotations

import asyncio
import logging

from app.bot_controls import can_execute, get_execution_mode
from app.config import settings
from app.exchange import get_exchange_client
from app.execution import execute_signal
from app.journal import log_bot_event
from app.scanner import get_active_signals, run_scan
from app.trade_management import manage_open_trades


logger = logging.getLogger(__name__)


async def auto_trading_loop() -> None:
    while True:
        try:
            client = get_exchange_client(get_execution_mode())
            management_result = await asyncio.to_thread(manage_open_trades, client)
            if not management_result.get("ok"):
                log_bot_event(
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

            allowed, reason = can_execute()
            if not allowed:
                if reason:
                    logger.debug("Auto trading blocked: %s", reason)
                await asyncio.sleep(settings.bot_scan_interval_seconds)
                continue

            result = await asyncio.to_thread(run_scan, client)
            if not result.get("ok"):
                log_bot_event(
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
                    log_bot_event(
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
                    log_bot_event(
                        "trade_executed",
                        f"Executed {signal.get('symbol')} in {get_execution_mode()} mode",
                        metadata={"trade": outcome.get("trade"), "signal": signal},
                    )
                else:
                    error_message = outcome.get("error", "Unknown execution failure")
                    logger.warning("Auto execution failed for %s: %s", signal.get("symbol"), error_message)
                    log_bot_event(
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
            log_bot_event(
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

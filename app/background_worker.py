from __future__ import annotations

import asyncio
import logging

from app.bot_controls import can_execute, get_execution_mode
from app.config import settings
from app.exchange import get_exchange_client
from app.execution import execute_signal
from app.journal import log_bot_event
from app.scanner import get_active_signals, run_scan


logger = logging.getLogger(__name__)


async def auto_trading_loop() -> None:
    while True:
        try:
            allowed, reason = can_execute()
            if not allowed:
                if reason:
                    logger.debug("Auto trading blocked: %s", reason)
                await asyncio.sleep(settings.bot_scan_interval_seconds)
                continue

            client = get_exchange_client(get_execution_mode())
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

            for signal in get_active_signals():
                outcome = await asyncio.to_thread(execute_signal, client, signal, True)
                if outcome.get("ok"):
                    log_bot_event(
                        "trade_executed",
                        f"Executed {signal.get('symbol')} in {get_execution_mode()} mode",
                        metadata={"trade": outcome.get("trade"), "signal": signal},
                    )
                elif outcome.get("error"):
                    logger.debug("Auto execution skipped for %s: %s", signal.get("symbol"), outcome.get("error"))
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

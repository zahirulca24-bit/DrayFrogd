from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected anchor not found in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/bot_controls.py",
    "from app.models import BotRuntimeConfig, RiskRuntimeState\n",
    "from app.models import BotRuntimeConfig, RiskRuntimeState\nfrom app.runtime_guard import get_watchdog_execution_block\n",
)
replace_once(
    "app/bot_controls.py",
    "    if row.emergency_stop:\n        return False, \"Emergency stop is active\"\n",
    "    if row.emergency_stop:\n        return False, \"Emergency stop is active\"\n    watchdog_blocked, watchdog_reason = get_watchdog_execution_block()\n    if watchdog_blocked:\n        return False, f\"Runtime watchdog blocked execution: {watchdog_reason or 'critical mismatch'}\"\n",
)

replace_once(
    "app/background_worker.py",
    "from app.runtime_integration import install_runtime_integration\n",
    "from app.runtime_integration import install_runtime_integration\nfrom app.runtime_watchdog import run_watchdog_cycle\n",
)
replace_once(
    "app/background_worker.py",
    "                allowed, reason = can_execute()\n",
    "                watchdog_result = await asyncio.to_thread(\n                    run_watchdog_cycle, client, reconciliation_result=reconciliation_result\n                )\n                if watchdog_result.get(\"execution_blocked\"):\n                    logger.warning(\"Runtime watchdog blocked new execution: %s\", watchdog_result.get(\"reasons\"))\n\n                allowed, reason = can_execute()\n",
)

replace_once(
    "app/schemas.py",
    "\n\nclass BacktestRequest(BaseModel):\n",
    "\n\nclass WatchdogConfigRequest(BaseModel):\n    enabled: bool | None = None\n    interval_seconds: int | None = None\n    action_mode: str | None = None\n    mismatch_tolerance_cycles: int | None = None\n    exposure_tolerance_ratio: float | None = None\n    pnl_tolerance: float | None = None\n\n\nclass BacktestRequest(BaseModel):\n",
)

replace_once(
    "app/main.py",
    "from app.active_trade_control import enrich_active_trades, request_market_close\n",
    "from app.active_trade_control import enrich_active_trades, request_market_close\nfrom app.authoritative_state import get_snapshot\n",
)
replace_once(
    "app/main.py",
    "from app.schemas import BacktestRequest, BotConfigRequest, ExecuteSignalRequest, LoginRequest, PositionSizeRequest, RiskSignalRequest, SessionVerifyResponse, TokenResponse\n",
    "from app.schemas import BacktestRequest, BotConfigRequest, ExecuteSignalRequest, LoginRequest, PositionSizeRequest, RiskSignalRequest, SessionVerifyResponse, TokenResponse, WatchdogConfigRequest\n",
)
replace_once(
    "app/main.py",
    "from app.watchdog import get_watchdog_snapshot\n",
    "from app.watchdog import get_watchdog_snapshot\nfrom app.runtime_watchdog import (\n    ensure_watchdog_state,\n    get_watchdog_incidents,\n    get_watchdog_runtime_status,\n    run_watchdog_cycle,\n    update_watchdog_config,\n)\n",
)
replace_once(
    "app/main.py",
    "    ensure_runtime_config()\n",
    "    ensure_runtime_config()\n    ensure_watchdog_state()\n",
)
replace_once(
    "app/main.py",
    "@app.get(\"/watchdog/status\")\ndef watchdog_status(_: dict = Depends(require_authenticated), limit: int = 100) -> dict:\n    global _background_task\n    worker_running = _background_task is not None and not _background_task.done()\n    return get_watchdog_snapshot(worker_running=worker_running)\n",
    "@app.get(\"/runtime/snapshot\")\ndef runtime_snapshot(_: dict = Depends(require_authenticated)) -> dict:\n    return get_snapshot()\n\n\n@app.get(\"/watchdog/status\")\ndef watchdog_status(_: dict = Depends(require_authenticated)) -> dict:\n    return get_watchdog_runtime_status()\n\n\n@app.get(\"/watchdog/operations\")\ndef watchdog_operations(_: dict = Depends(require_authenticated)) -> dict:\n    global _background_task\n    worker_running = _background_task is not None and not _background_task.done()\n    return get_watchdog_snapshot(worker_running=worker_running)\n\n\n@app.get(\"/watchdog/incidents\")\ndef watchdog_incidents(limit: int = 100, _: dict = Depends(require_authenticated)) -> dict:\n    return {\"incidents\": get_watchdog_incidents(limit=max(10, min(limit, 300)))}\n\n\n@app.post(\"/watchdog/config\")\ndef watchdog_config(payload: WatchdogConfigRequest, _: dict = Depends(require_authenticated)) -> dict:\n    try:\n        return update_watchdog_config(**payload.model_dump())\n    except ValueError as exc:\n        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc\n\n\n@app.post(\"/watchdog/run-now\")\ndef watchdog_run_now(_: dict = Depends(require_authenticated)) -> dict:\n    client = get_exchange_client(get_execution_mode())\n    reconciliation_result = reconcile_state(client)\n    return run_watchdog_cycle(client, reconciliation_result=reconciliation_result)\n",
)

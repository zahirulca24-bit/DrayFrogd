import asyncio
from typing import Any
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.active_trade_control import enrich_active_trades, request_market_close
from app.auth import authenticate_admin, create_session_token, is_auth_configured
from app.background_worker import auto_trading_loop
from app.bot_controls import (
    activate_emergency_stop,
    can_execute,
    ensure_runtime_config,
    get_bot_status,
    get_execution_mode,
    resume_bot,
    start_bot,
    stop_bot,
    update_bot_config,
)
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.dependencies import require_authenticated
from app.execution import execute_signal, get_active_trades, get_closed_trades, replace_active_trades
from app.exchange import get_exchange_client
from app.journal import create_trade_entry, get_bot_events, get_closed_trade_history, get_open_trade_history, get_trade_history, log_bot_event
from app.metrics import get_metrics, get_portfolio_summary
from app.middleware import AuthMiddleware
from app.models import UserSession
from app.position_sizing import calculate_position_size
from app.readiness import get_readiness_status
from app.reconciliation import reconcile_state
from app.risk import get_risk_state, validate_trade
from app.scanner import SCANNER_SYMBOLS, get_active_signals, get_latest_signals, run_scan
from app.schemas import BotConfigRequest, ExecuteSignalRequest, LoginRequest, PositionSizeRequest, RiskSignalRequest, SessionVerifyResponse, TokenResponse
from app.symbols import get_symbol_metadata, refresh_symbol_metadata
from app.trade_management import manage_open_trades
from app.watchdog import get_watchdog_snapshot


app = FastAPI(title=settings.app_name)
_background_task: asyncio.Task | None = None

app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        settings.frontend_url,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    global _background_task
    Base.metadata.create_all(bind=engine)
    ensure_runtime_config()
    if not get_active_trades():
        replace_active_trades(get_open_trade_history())
    if _background_task is None or _background_task.done():
        _background_task = asyncio.create_task(auto_trading_loop())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _background_task
    if _background_task is not None:
        _background_task.cancel()
        try:
            await _background_task
        except asyncio.CancelledError:
            pass
        _background_task = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    if not is_auth_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth is not configured")

    if not authenticate_admin(payload.username, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    try:
        token, token_id = create_session_token(payload.username)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    db = SessionLocal()
    try:
        db.add(UserSession(username=payload.username, token_id=token_id))
        db.commit()
    finally:
        db.close()

    return TokenResponse(access_token=token)


@app.get("/session/verify", response_model=SessionVerifyResponse)
def verify_session(session: dict = Depends(require_authenticated)) -> SessionVerifyResponse:
    return SessionVerifyResponse(authenticated=True, username=session["sub"])


@app.get("/exchange/status")
def exchange_status() -> dict:
    mode = get_execution_mode()
    demo = get_exchange_client("demo").get_status()
    live = get_exchange_client("live").get_status()
    return {
        "mode": mode,
        "demo": demo,
        "live": live,
        "demo_only": mode == "demo",
        "base_url": demo["base_url"] if mode == "demo" else live["base_url"],
        "api_keys_present": demo["api_keys_present"] if mode == "demo" else live["api_keys_present"],
        "reachable": demo["reachable"] if mode == "demo" else live["reachable"],
        "error": demo["error"] if mode == "demo" else live["error"],
    }


@app.get("/account")
def account(_: dict = Depends(require_authenticated)) -> dict:
    client = get_exchange_client(get_execution_mode())
    wallet_ok, wallet_data, wallet_error = client.safe_fetch_wallet_balance()
    positions_ok, positions_data, positions_error = client.safe_fetch_positions()

    return {
        "ok": wallet_ok and positions_ok,
        "mode": get_execution_mode(),
        "wallet": {"ok": wallet_ok, "data": wallet_data, "error": wallet_error},
        "positions": {"ok": positions_ok, "data": positions_data, "error": positions_error},
    }


@app.get("/symbols")
def symbols(category: str = "linear", symbol: str | None = None) -> dict:
    client = get_exchange_client(get_execution_mode())
    refreshed = refresh_symbol_metadata(client=client, category=category, symbol=symbol)

    if not refreshed["ok"]:
        return {
            "ok": False,
            "category": category,
            "symbols": get_symbol_metadata(category=category, symbol=symbol),
            "error": refreshed["error"],
        }

    return {
        "ok": True,
        "category": category,
        "symbols": refreshed["symbols"],
        "error": None,
    }


@app.get("/market/candles")
def market_candles(
    symbol: str = "BTCUSDT",
    interval: str = "1",
    limit: int = 120,
    _: dict = Depends(require_authenticated),
) -> dict:
    client = get_exchange_client(get_execution_mode())
    ok, candles, error = client.safe_fetch_recent_candles(symbol=symbol.upper(), interval=interval, limit=max(20, min(limit, 300)))
    return {
        "ok": ok,
        "symbol": symbol.upper(),
        "interval": interval,
        "candles": candles if ok else [],
        "error": error,
    }


@app.get("/market/orderbook")
def market_orderbook(
    symbol: str = "BTCUSDT",
    limit: int = 20,
    _: dict = Depends(require_authenticated),
) -> dict:
    client = get_exchange_client(get_execution_mode())
    ok, orderbook, error = client.safe_fetch_orderbook(symbol=symbol.upper(), limit=max(5, min(limit, 50)))
    return {
        "ok": ok,
        "symbol": symbol.upper(),
        "orderbook": orderbook or {"bids": [], "asks": []},
        "error": error,
    }


@app.get("/market/overview")
def market_overview(_: dict = Depends(require_authenticated)) -> dict:
    client = get_exchange_client(get_execution_mode())
    ok, tickers, error = client.safe_fetch_market_tickers()
    if not ok:
        return {
            "ok": False,
            "server_time": None,
            "top_gainers": [],
            "watchlist": [],
            "error": error,
        }

    normalized = [_normalize_ticker(item) for item in tickers]
    filtered = [item for item in normalized if item["symbol"].endswith("USDT")]
    top_gainers = sorted(filtered, key=lambda item: item["price24hPcnt"], reverse=True)[:20]
    watchlist_symbols = set(SCANNER_SYMBOLS)
    watchlist = [item for item in filtered if item["symbol"] in watchlist_symbols]
    watchlist.sort(key=lambda item: SCANNER_SYMBOLS.index(item["symbol"]) if item["symbol"] in SCANNER_SYMBOLS else 999)

    return {
        "ok": True,
        "server_time": _utc_now_iso(),
        "top_gainers": top_gainers,
        "watchlist": watchlist,
        "error": None,
    }


@app.get("/readiness")
def readiness() -> dict:
    return get_readiness_status()


def _run_scan_cycle(mode: str, *, trigger: str) -> dict:
    client = get_exchange_client(mode)
    scan_result = run_scan(client)
    execution_attempts: list[dict] = []
    blocked_reason: str | None = None

    if scan_result.get("ok"):
        signals = scan_result.get("signals") or []
        allowed, reason = can_execute()
        if signals and allowed:
            for signal in signals:
                outcome = execute_signal(client, signal, True)
                execution_attempts.append(
                    {
                        "symbol": signal.get("symbol"),
                        "ok": outcome.get("ok", False),
                        "error": outcome.get("error"),
                        "trade": outcome.get("trade"),
                    }
                )
                if outcome.get("ok"):
                    log_bot_event(
                        "trade_executed",
                        f"Executed {signal.get('symbol')} in {mode} mode",
                        metadata={"trade": outcome.get("trade"), "signal": signal, "trigger": trigger},
                    )
                else:
                    log_bot_event(
                        "auto_execution_failed",
                        f"Auto execution failed for {signal.get('symbol')}",
                        level="warning",
                        metadata={
                            "endpoint": f"{trigger}:auto_execution",
                            "affected_module": "execution",
                            "error_code": "AUTO_EXECUTION_FAILED",
                            "signal": signal,
                            "outcome": outcome,
                            "error": outcome.get("error", "Unknown execution failure"),
                        },
                    )
        elif signals:
            blocked_reason = reason or "Auto execution is blocked"
            for signal in signals:
                execution_attempts.append(
                    {
                        "symbol": signal.get("symbol"),
                        "ok": False,
                        "error": blocked_reason,
                        "trade": None,
                    }
                )

    return {
        **scan_result,
        "scanned_symbols": scan_result.get("symbols_scanned", 0),
        "execution_attempted": len(execution_attempts) > 0,
        "executions": execution_attempts,
        "executed": sum(1 for item in execution_attempts if item.get("ok")),
        "execution_blocked_reason": blocked_reason,
    }


@app.post("/scanner/run")
async def scanner_run(_: dict = Depends(require_authenticated)) -> dict:
    mode = get_execution_mode()
    client = get_exchange_client(mode)
    result = await asyncio.to_thread(run_scan, client)
    log_bot_event("scanner_run", "Scanner executed manually (scan-only diagnostic)", metadata={"mode": mode, "result": result})
    return result


@app.get("/scanner/results")
def scanner_results(_: dict = Depends(require_authenticated)) -> dict:
    return {"signals": get_latest_signals()}


@app.get("/signals")
def signals(_: dict = Depends(require_authenticated)) -> dict:
    return {"signals": get_active_signals()}


@app.post("/risk/validate")
def risk_validate(payload: RiskSignalRequest, _: dict = Depends(require_authenticated)) -> dict:
    return validate_trade(payload.model_dump())


@app.get("/risk/state")
def risk_state(_: dict = Depends(require_authenticated)) -> dict:
    return get_risk_state()


@app.post("/position-size/calculate")
def position_size_calculate(payload: PositionSizeRequest, _: dict = Depends(require_authenticated)) -> dict:
    client = get_exchange_client(get_execution_mode())
    signal = payload.model_dump()

    validation = validate_trade(signal)
    if not validation.get("allowed"):
        return {"allowed": False, "reason": validation.get("reason", "Risk validation failed"), "quantity": None}

    ok_symbol, symbol_infos, symbol_error = client.safe_fetch_symbol_info(symbol=payload.symbol.upper())
    if not ok_symbol or not symbol_infos:
        return {"allowed": False, "reason": symbol_error or "Symbol info unavailable", "quantity": None}

    ok_wallet, wallet, wallet_error = client.safe_fetch_wallet_balance()
    if not ok_wallet or wallet is None:
        return {"allowed": False, "reason": wallet_error or "Wallet balance unavailable", "quantity": None}

    ok_positions, positions, positions_error = client.safe_fetch_positions()
    if not ok_positions:
        return {"allowed": False, "reason": positions_error or "Position data unavailable", "quantity": None}

    return calculate_position_size(
        signal=signal,
        wallet=wallet,
        symbol_info=symbol_infos[0],
        active_trades=get_active_trades(),
        positions=positions,
        settings=validation,
        client=client,
    )


@app.post("/execute")
def execute(payload: ExecuteSignalRequest, _: dict = Depends(require_authenticated)) -> dict:
    result = execute_signal(get_exchange_client(get_execution_mode()), payload.model_dump())
    if not result.get("ok"):
        log_bot_event(
            "execution_failed",
            str(result.get("error") or "Execution failed"),
            level="warning",
            metadata={
                "endpoint": "/execute",
                "affected_module": "execution",
                "error_code": "EXECUTION_FAILED",
                "retry_count": 0,
                "error": result.get("error"),
                "symbol": payload.symbol,
            },
        )
    return result


@app.get("/active-trades")
def active_trades(_: dict = Depends(require_authenticated)) -> dict:
    trades = get_active_trades()
    if not trades:
        trades = get_open_trade_history()
        if trades:
            replace_active_trades(trades)

    mode = get_execution_mode()
    client = get_exchange_client(mode)
    ok_positions, positions, positions_error = client.safe_fetch_positions()
    trades = enrich_active_trades(trades, positions if ok_positions else [], mode)
    replace_active_trades(trades)
    return {
        "trades": trades,
        "positions_synced": ok_positions,
        "error": positions_error,
    }


@app.post("/active-trades/{journal_id}/market-close")
def active_trade_market_close(journal_id: str, _: dict = Depends(require_authenticated)) -> dict:
    return request_market_close(
        get_exchange_client(get_execution_mode()),
        journal_id,
    )


@app.get("/trade-history")
def trade_history(_: dict = Depends(require_authenticated)) -> dict:
    history = get_closed_trades() or get_closed_trade_history()
    return {"trades": history}


@app.get("/journal/trades")
def journal_trades(_: dict = Depends(require_authenticated)) -> dict:
    return {"trades": get_trade_history()}


@app.get("/bot/events")
def bot_events(_: dict = Depends(require_authenticated), limit: int = 100) -> dict:
    return {"events": get_bot_events(limit=max(10, min(limit, 300)))}


@app.get("/watchdog/status")
def watchdog_status(_: dict = Depends(require_authenticated)) -> dict:
    global _background_task
    worker_running = _background_task is not None and not _background_task.done()
    return get_watchdog_snapshot(worker_running=worker_running)


@app.post("/reconcile")
def reconcile(_: dict = Depends(require_authenticated)) -> dict:
    return reconcile_state(get_exchange_client(get_execution_mode()))


@app.post("/trade-management/run")
def trade_management_run(_: dict = Depends(require_authenticated)) -> dict:
    return manage_open_trades(get_exchange_client(get_execution_mode()))


@app.get("/metrics")
def metrics(_: dict = Depends(require_authenticated)) -> dict:
    return get_metrics()


@app.get("/portfolio")
def portfolio(_: dict = Depends(require_authenticated)) -> dict:
    return get_portfolio_summary()


@app.post("/bot/start")
def bot_start(_: dict = Depends(require_authenticated)) -> dict:
    update_bot_config(
        execution_mode="demo",
        auto_trading_enabled=True,
    )
    resume_bot()
    state = start_bot()
    cycle = _run_scan_cycle("demo", trigger="/bot/start")

    log_bot_event(
        "bot_start",
        "Bot started in full automatic demo mode",
        metadata={
            **state,
            "scan_started": True,
            "scan_ok": cycle.get("ok", False),
            "scanned_symbols": cycle.get("scanned_symbols", 0),
            "signals_generated": len(cycle.get("signals") or []),
            "executed": cycle.get("executed", 0),
            "execution_blocked_reason": cycle.get("execution_blocked_reason"),
        },
    )

    return {
        **state,
        "scan": cycle,
        "automation": {
            "demo_mode": True,
            "auto_trading": True,
            "worker_loop": True,
            "trade_management": True,
            "immediate_execution": True,
        },
    }


@app.post("/bot/stop")
def bot_stop(_: dict = Depends(require_authenticated)) -> dict:
    state = stop_bot()
    log_bot_event("bot_stop", "Bot stopped", metadata=state)
    return state


@app.get("/bot/status")
def bot_status(_: dict = Depends(require_authenticated)) -> dict:
    readiness = get_readiness_status()
    state = get_bot_status()
    return {**state, "readiness": readiness}


@app.post("/bot/config")
def bot_config(payload: BotConfigRequest, _: dict = Depends(require_authenticated)) -> dict:
    try:
        state = update_bot_config(
            execution_mode=payload.execution_mode,
            auto_trading_enabled=payload.auto_trading_enabled,
            risk_per_trade=payload.risk_per_trade,
            leverage_cap=payload.leverage_cap,
            exposure_cap=payload.exposure_cap,
            max_open_trades=payload.max_open_trades,
            max_daily_trades=payload.max_daily_trades,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    log_bot_event("bot_config_updated", "Bot config updated", metadata=state)
    return {**state, "readiness": get_readiness_status()}


@app.post("/bot/emergency-stop")
def bot_emergency_stop(_: dict = Depends(require_authenticated)) -> dict:
    state = activate_emergency_stop()
    log_bot_event("bot_emergency_stop", "Emergency stop activated", level="warning", metadata=state)
    return state


@app.post("/bot/resume")
def bot_resume(_: dict = Depends(require_authenticated)) -> dict:
    state = resume_bot()
    log_bot_event("bot_resume", "Bot resumed", metadata=state)
    return state


def _normalize_ticker(item: dict) -> dict:
    return {
        "symbol": str(item.get("symbol", "")).upper(),
        "lastPrice": _to_float(item.get("lastPrice")),
        "price24hPcnt": _to_float(item.get("price24hPcnt")),
        "volume24h": _to_float(item.get("volume24h")),
        "turnover24h": _to_float(item.get("turnover24h")),
        "highPrice24h": _to_float(item.get("highPrice24h")),
        "lowPrice24h": _to_float(item.get("lowPrice24h")),
    }


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _merge_exchange_positions_into_trades(trades: list[dict[str, Any]], positions: list[dict[str, Any]], execution_mode: str) -> list[dict[str, Any]]:
    merged = [dict(trade) for trade in trades]
    trades_by_symbol = {str(trade.get("symbol", "")).upper(): trade for trade in merged}

    for position in positions:
        try:
            size = float(position.get("size", 0))
        except (TypeError, ValueError):
            continue
        if size <= 0:
            continue

        symbol = str(position.get("symbol", "")).upper()
        if not symbol:
            continue

        direction = "short" if str(position.get("side", "")).lower() == "sell" else "long"
        entry = _to_float(position.get("avgPrice")) or 0.0
        mark_price = _to_float(position.get("markPrice")) or entry
        stop_loss = _to_float(position.get("stopLoss")) or entry
        take_profit = _to_float(position.get("takeProfit")) or entry
        existing = trades_by_symbol.get(symbol)

        if existing:
            existing["quantity"] = position.get("size", existing.get("quantity"))
            existing["remaining_quantity"] = position.get("size", existing.get("remaining_quantity", existing.get("quantity")))
            existing["entry"] = entry or _to_float(existing.get("entry")) or 0.0
            existing["direction"] = existing.get("direction") or direction
            existing["status"] = "active"
            existing["mark_price"] = mark_price
            if not _to_float(existing.get("stop_loss")):
                existing["stop_loss"] = stop_loss
            if not _to_float(existing.get("take_profit")):
                existing["take_profit"] = take_profit
            continue

        trade = {
            "symbol": symbol,
            "strategy_name": "unknown",
            "strategy": "unknown",
            "direction": direction,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "quantity": position.get("size"),
            "remaining_quantity": position.get("size"),
            "status": "active",
            "opened_at": _utc_now_iso(),
            "execution_mode": execution_mode,
            "order_id": None,
            "journal_id": f"exchange-{execution_mode}-{symbol}",
            "mark_price": mark_price,
            "exchange_metadata": {
                "source": "exchange_position_only",
                "position_snapshot": position,
            },
        }
        journal = create_trade_entry(trade)
        trade["journal_id"] = journal["journal_id"]
        merged.append(trade)
        trades_by_symbol[symbol] = trade

    return merged

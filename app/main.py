import asyncio

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.auth import authenticate_admin, create_session_token, is_auth_configured
from app.background_worker import auto_trading_loop
from app.bot_controls import (
    activate_emergency_stop,
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
from app.execution import execute_signal, get_active_trades, get_closed_trades
from app.exchange import get_exchange_client
from app.journal import get_closed_trade_history, get_trade_history, log_bot_event
from app.metrics import get_metrics, get_portfolio_summary
from app.middleware import AuthMiddleware
from app.models import UserSession
from app.readiness import get_readiness_status
from app.reconciliation import reconcile_state
from app.risk import get_risk_state, validate_trade
from app.scanner import get_active_signals, get_latest_signals, run_scan
from app.schemas import BotConfigRequest, ExecuteSignalRequest, LoginRequest, RiskSignalRequest, SessionVerifyResponse, TokenResponse
from app.symbols import get_symbol_metadata, refresh_symbol_metadata


app = FastAPI(title=settings.app_name)
_background_task: asyncio.Task | None = None
_scanner_task: asyncio.Task | None = None

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


@app.get("/readiness")
def readiness() -> dict:
    return get_readiness_status()


async def _run_scanner_job(mode: str) -> None:
    client = get_exchange_client(mode)
    try:
        result = await asyncio.to_thread(run_scan, client)
        log_bot_event("scanner_run", "Scanner executed manually", metadata={"mode": mode, "result": result})
    except Exception as exc:
        log_bot_event("scanner_run", "Scanner execution failed", level="error", metadata={"mode": mode, "error": str(exc)})


@app.post("/scanner/run")
async def scanner_run(_: dict = Depends(require_authenticated)) -> dict:
    global _scanner_task

    mode = get_execution_mode()
    if _scanner_task is None or _scanner_task.done():
        _scanner_task = asyncio.create_task(_run_scanner_job(mode))

    return {"ok": True, "queued": True, "mode": mode}


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


@app.post("/execute")
def execute(payload: ExecuteSignalRequest, _: dict = Depends(require_authenticated)) -> dict:
    return execute_signal(get_exchange_client(get_execution_mode()), payload.model_dump())


@app.get("/active-trades")
def active_trades(_: dict = Depends(require_authenticated)) -> dict:
    return {"trades": get_active_trades()}


@app.get("/trade-history")
def trade_history(_: dict = Depends(require_authenticated)) -> dict:
    history = get_closed_trades() or get_closed_trade_history()
    return {"trades": history}


@app.get("/journal/trades")
def journal_trades(_: dict = Depends(require_authenticated)) -> dict:
    return {"trades": get_trade_history()}


@app.post("/reconcile")
def reconcile(_: dict = Depends(require_authenticated)) -> dict:
    return reconcile_state(get_exchange_client(get_execution_mode()))


@app.get("/metrics")
def metrics(_: dict = Depends(require_authenticated)) -> dict:
    return get_metrics()


@app.get("/portfolio")
def portfolio(_: dict = Depends(require_authenticated)) -> dict:
    return get_portfolio_summary()


@app.post("/bot/start")
def bot_start(_: dict = Depends(require_authenticated)) -> dict:
    state = start_bot()
    log_bot_event("bot_start", "Bot started", metadata=state)
    return state


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

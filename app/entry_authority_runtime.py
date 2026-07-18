from __future__ import annotations

from typing import Any

from fastapi import Request
from pydantic import BaseModel, ValidationError
from starlette.responses import JSONResponse

from app.bot_controls import get_execution_mode
from app.exchange import get_exchange_client
from app.journal import log_bot_event
from app.scalping_entry_authority import APPROVE, MISSED, evaluate_entry_authority_from_client

ENTRY_AUTHORITY_DRY_RUN_PATH = "/entry-authority/dry-run"


class EntryAuthorityDryRunPayload(BaseModel):
    symbol: str
    strategy_name: str | None = None
    strategy: str | None = None
    trade_type: str = "scalping"
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float | None = None
    detected_at: str | None = None
    status: str = "active"
    allowed_entry_min: float | None = None
    allowed_entry_max: float | None = None


async def handle_entry_authority_dry_run(request: Request) -> JSONResponse:
    """Authenticated runtime dry-run endpoint for the scalping Entry Authority.

    This endpoint is intentionally non-executing. It fetches live market evidence,
    runs the dry-run worker, logs the decision, and returns the audit decision.
    No order submission API is called here.
    """

    if request.method.upper() != "POST":
        return JSONResponse(status_code=405, content={"detail": "Method Not Allowed"})

    if getattr(request.state, "session", None) is None:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    try:
        raw_payload = await request.json()
        payload = EntryAuthorityDryRunPayload(**raw_payload)
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid JSON payload"})

    signal = _model_to_dict(payload)
    mode = get_execution_mode()
    result = evaluate_entry_authority_from_client(
        get_exchange_client(mode),
        signal,
    )

    _safe_log_decision(signal=signal, result=result, mode=mode)
    return JSONResponse(status_code=200, content=result)


def _model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _safe_log_decision(*, signal: dict[str, Any], result: dict[str, Any], mode: str) -> None:
    decision = str(result.get("decision") or "UNKNOWN")
    level = "info" if decision in {APPROVE, MISSED} else "warning"
    try:
        log_bot_event(
            "entry_authority_dry_run",
            f"Entry authority dry-run {decision} for {signal.get('symbol')}",
            level=level,
            metadata={
                "endpoint": ENTRY_AUTHORITY_DRY_RUN_PATH,
                "mode": mode,
                "signal": signal,
                "result": result,
                "order_submission": False,
            },
        )
    except Exception:
        # Logging must not turn a read-only dry-run decision into an endpoint error.
        pass

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

_INSTALLED = False
_ORIGINAL_AUTHORITATIVE_EXECUTE: Callable[..., dict[str, Any]] | None = None


def install() -> None:
    """Place the daily-loss gate on the public production order-entry boundary.

    The public API keeps its existing spread gate and test seam. The underlying
    execution_service function remains directly testable without exchange-ledger
    preflight; production callers use app.execution, whose authoritative delegate
    is guarded immediately before reservation/order placement.
    """

    global _INSTALLED, _ORIGINAL_AUTHORITATIVE_EXECUTE
    if _INSTALLED:
        return

    import app.batch1_execution_safety as safety
    import app.execution as execution
    import app.execution_service as execution_service
    import app.risk as risk

    original_authoritative = execution_service.execute_signal
    _ORIGINAL_AUTHORITATIVE_EXECUTE = original_authoritative

    @wraps(original_authoritative)
    def guarded_authoritative_execute(
        client: Any,
        signal: dict[str, Any],
        auto_triggered: bool = False,
    ) -> dict[str, Any]:
        authority = safety.get_daily_loss_authority(client=client, force=True)
        if not authority.get("ok"):
            return {
                "ok": False,
                "error": "DAILY_LOSS_AUTHORITY_UNAVAILABLE",
                "detail": authority.get("error") or "Bybit daily loss authority is unavailable",
                "daily_loss_authority": authority,
            }

        wallet_ok, wallet, wallet_error = client.safe_fetch_wallet_balance()
        if not wallet_ok or wallet is None:
            return {
                "ok": False,
                "error": "WALLET_STATE_UNAVAILABLE",
                "detail": wallet_error or "Wallet balance unavailable",
                "daily_loss_authority": authority,
            }

        account_equity = risk.extract_account_equity(wallet)
        if account_equity is None:
            return {
                "ok": False,
                "error": "EQUITY_UNAVAILABLE",
                "detail": "Fresh account equity is unavailable",
                "daily_loss_authority": authority,
            }

        risk_state = risk.refresh_risk_state(account_equity=account_equity)
        if risk_state.get("circuit_breaker_active"):
            return {
                "ok": False,
                "error": "DAILY_LOSS_CIRCUIT_BREAKER",
                "detail": risk_state.get("circuit_breaker_reason") or "Daily loss circuit breaker is active",
                "daily_loss_authority": authority,
                "risk_state": risk_state,
            }

        return safety.normalize_execution_block(
            original_authoritative(client, signal, auto_triggered)
        )

    # Do not replace execution_service.execute_signal itself: it is the internal
    # service seam. Only the public execution module's delegate is production-gated.
    execution._execute_signal_authoritatively = guarded_authoritative_execute

    # Restore the existing public execution function so spread validation remains
    # outside the authoritative daily-loss/order boundary.
    if safety._ORIGINAL_EXECUTE_SIGNAL is not None:
        execution.execute_signal = safety._ORIGINAL_EXECUTE_SIGNAL

    # These modules imported the temporary outer wrapper during Batch-1 install.
    # Rebind them to the restored public API; it now calls the guarded inner path.
    try:
        import app.risk_execution as risk_execution

        risk_execution.execute_signal = execution.execute_signal
    except Exception:
        pass
    try:
        import app.background_worker as background_worker

        background_worker.execute_signal = execution.execute_signal
    except Exception:
        pass

    _INSTALLED = True

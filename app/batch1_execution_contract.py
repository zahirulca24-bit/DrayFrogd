from __future__ import annotations

from functools import wraps
from typing import Any, Callable

_INSTALLED = False
_ORIGINAL_AUTHORITATIVE_EXECUTE: Callable[..., dict[str, Any]] | None = None


def install() -> None:
    """Place the daily-loss gate on the public production order-entry boundary.

    The public API keeps its existing spread gate and test seam. The underlying
    execution_service function remains directly testable without exchange-ledger
    preflight; production callers use the installed public executor, whose
    authoritative delegate is guarded immediately before reservation/order
    placement.
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
            error_code = authority.get("error")
            if error_code not in ("DAILY_LOSS_AUTHORITY_UNAVAILABLE", "DAILY_LOSS_DATA_INCONSISTENT"):
                error_code = "DAILY_LOSS_AUTHORITY_UNAVAILABLE"
            return {
                "ok": False,
                "error": error_code,
                "detail": authority.get("detail") or authority.get("error") or "Daily loss authority is unavailable",
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

    # The authoritative internal delegate remains protected by the existing
    # daily-loss authority. The installed public executor adds fee-budget and
    # protected-position degradation rules around this guarded delegate.
    execution._execute_signal_authoritatively = guarded_authoritative_execute

    import app.risk_execution as risk_execution

    execution.execute_signal = risk_execution.execute_signal

    # Long-lived imports must share the exact same installed executor.
    try:
        import app.background_worker as background_worker

        background_worker.execute_signal = execution.execute_signal
    except Exception:
        pass

    _INSTALLED = True

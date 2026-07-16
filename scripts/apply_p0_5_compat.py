from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"P0-5 compatibility anchor not found in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/authoritative_risk_engine.py",
    '''    if detected_at is not None:\n        max_age = max(int(settings.risk_signal_max_age_seconds), 1)\n        age_seconds = (current - detected_at).total_seconds()\n        if age_seconds < -5:\n            return _reject("SIGNAL_TIMESTAMP_INVALID", "Signal detected_at timestamp is in the future")\n        if age_seconds > max_age:\n            return _reject(\n                "SIGNAL_STALE",\n                f"Signal age {age_seconds:.0f}s exceeds the {max_age}s execution limit",\n            )\n''',
    '''    if detected_at is not None and normalized.get("auto_triggered"):\n        max_age = max(int(settings.risk_signal_max_age_seconds), 1)\n        age_seconds = (current - detected_at).total_seconds()\n        if age_seconds < -5:\n            return _reject("SIGNAL_TIMESTAMP_INVALID", "Signal detected_at timestamp is in the future")\n        if age_seconds > max_age:\n            return _reject(\n                "SIGNAL_STALE",\n                f"Signal age {age_seconds:.0f}s exceeds the {max_age}s execution limit",\n            )\n''',
)

replace_once(
    "app/authoritative_risk_engine.py",
    '''    risk_state: dict[str, Any] | None = None,\n) -> dict[str, Any]:\n''',
    '''    risk_state: dict[str, Any] | None = None,\n    execution_mode: str | None = None,\n) -> dict[str, Any]:\n''',
)
replace_once(
    "app/authoritative_risk_engine.py",
    '''    mode = get_execution_mode()\n''',
    '''    mode = str(execution_mode or get_execution_mode()).lower().strip()\n''',
)
replace_once(
    "app/authoritative_risk_engine.py",
    '''    existing = get_trade_by_execution_key(execution_key)\n    if existing is not None:\n        return _reject(\n            "SIGNAL_ALREADY_CONSUMED",\n            "This exact signal already has a journal lifecycle and cannot be executed again",\n            execution_key=execution_key,\n            journal_id=existing.get("journal_id"),\n            existing_status=existing.get("status"),\n        )\n\n''',
    '''    # Duplicate execution, same-symbol cooldown, daily count and risk capacity\n    # are enforced atomically by reserve_execution_capacity after this signed\n    # decision is consumed. A pre-approval Journal query would introduce a\n    # second database dependency and a time-of-check/time-of-use race.\n''',
)

replace_once(
    "app/execution_service.py",
    '''    approval = issue_execution_approval(\n''',
    '''    execution_mode = get_execution_mode()\n    approval = issue_execution_approval(\n''',
)
replace_once(
    "app/execution_service.py",
    '''        risk_state=risk_state,\n    )\n''',
    '''        risk_state=risk_state,\n        execution_mode=execution_mode,\n    )\n''',
)
replace_once(
    "app/execution_service.py",
    '''    execution_mode = get_execution_mode()\n    approval_decision = dict(approval.get("decision") or {})\n''',
    '''    approval_decision = dict(approval.get("decision") or {})\n''',
)

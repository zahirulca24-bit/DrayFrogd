from pathlib import Path

path = Path("app/close_fill_sync.py")
source = path.read_text(encoding="utf-8")

old_error_precedence = "    return None, ledger_error or exact_error\n"
new_error_precedence = "    return None, exact_error or ledger_error\n"
if source.count(old_error_precedence) != 1:
    raise SystemExit("expected close error precedence block was not found exactly once")
source = source.replace(old_error_precedence, new_error_precedence, 1)

old_quantity_resolver = '''def _initial_quantity(trade: dict[str, Any]) -> float | None:\n    management = trade.get("management") if isinstance(trade.get("management"), dict) else {}\n    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}\n    metadata_management = metadata.get("management") if isinstance(metadata.get("management"), dict) else {}\n    for value in (\n        management.get("initial_quantity"),\n        metadata_management.get("initial_quantity"),\n        trade.get("quantity"),\n        trade.get("remaining_quantity"),\n    ):\n        numeric = _number(value)\n        if numeric is not None and numeric > 0:\n            return numeric\n    return None\n'''
new_quantity_resolver = '''def _initial_quantity(trade: dict[str, Any]) -> float | None:\n    management = trade.get("management") if isinstance(trade.get("management"), dict) else {}\n    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}\n    metadata_management = metadata.get("management") if isinstance(metadata.get("management"), dict) else {}\n    candidates = [\n        _number(trade.get("initial_quantity")),\n        _number(trade.get("quantity")),\n        _number(trade.get("remaining_quantity")),\n        _number(management.get("initial_quantity")),\n        _number(metadata_management.get("initial_quantity")),\n    ]\n    positive = [value for value in candidates if value is not None and value > 0]\n    if not positive:\n        return None\n\n    # The initial quantity cannot be smaller than a confirmed current/remaining\n    # quantity. Selecting the largest persisted candidate is fail-safe when old\n    # management metadata conflicts with a newer journal or exchange quantity:\n    # it prevents a partial close from being accepted as a complete close.\n    return max(positive)\n'''
if source.count(old_quantity_resolver) != 1:
    raise SystemExit("expected initial quantity resolver was not found exactly once")
source = source.replace(old_quantity_resolver, new_quantity_resolver, 1)

path.write_text(source, encoding="utf-8")

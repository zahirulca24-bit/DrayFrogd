from app.exchange_journal_backfill import _role_and_side


def test_plain_buy_preserves_side_for_lifecycle_inference() -> None:
    assert _role_and_side({"direction": "Buy"}) == (None, "buy")


def test_plain_sell_preserves_side_for_lifecycle_inference() -> None:
    assert _role_and_side({"direction": "Sell"}) == (None, "sell")

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.exchange import ExchangeError
from app.trade_management import _set_protection


class NotModifiedProtectionClient:
    def __init__(self) -> None:
        self.position = {
            "symbol": "SOLUSDT",
            "side": "Sell",
            "size": "14.9",
            "stopLoss": "75.55",
            "takeProfit": "74.43",
        }

    def set_trading_stop(self, symbol: str, take_profit: str, stop_loss: str):
        raise ExchangeError("not modified")

    def safe_fetch_positions(self):
        return True, [dict(self.position)], None


class TradeManagementProtectionTests(unittest.TestCase):
    def test_not_modified_protection_does_not_log_incident_when_exchange_matches(self) -> None:
        client = NotModifiedProtectionClient()
        trade = {"symbol": "SOLUSDT", "direction": "short"}

        with patch("app.trade_management.log_bot_event") as log_event:
            result = _set_protection(client, trade, stop_loss=75.55, take_profit=74.43)

        self.assertTrue(result["ok"])
        self.assertTrue(result["noop"])
        log_event.assert_not_called()

    def test_not_modified_protection_still_errors_when_exchange_does_not_match(self) -> None:
        client = NotModifiedProtectionClient()
        client.position["stopLoss"] = "75.99"
        trade = {"symbol": "SOLUSDT", "direction": "short"}

        with patch("app.trade_management.log_bot_event") as log_event:
            result = _set_protection(client, trade, stop_loss=75.55, take_profit=74.43)

        self.assertIn("error", result)
        log_event.assert_called_once()


if __name__ == "__main__":
    unittest.main()

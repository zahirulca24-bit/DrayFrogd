from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.metrics import get_metrics


NOW = datetime(2026, 7, 12, 19, 0, tzinfo=UTC)  # 13 July 2026, 01:00 BDT


class MetricsPartialRealizedTests(unittest.TestCase):
    def test_win_loss_counts_use_realized_pnl_and_profit_loss_synonyms(self) -> None:
        closed_profit = {
            "journal_id": "jrnl-profit",
            "status": "closed",
            "result": "profit",
            "closed_at": "2026-07-12T18:10:00+00:00",
            "realized_pnl": None,
            "fees": 0.1,
            "exchange_metadata": {},
        }
        closed_loss = {
            "journal_id": "jrnl-loss",
            "status": "closed",
            "result": None,
            "closed_at": "2026-07-12T18:20:00+00:00",
            "realized_pnl": -2.5,
            "fees": 0.2,
            "exchange_metadata": {},
        }
        closed_unknown = {
            "journal_id": "jrnl-unknown",
            "status": "closed",
            "result": "reconciliation_stale",
            "closed_at": "2026-07-12T18:30:00+00:00",
            "realized_pnl": None,
            "fees": None,
            "exchange_metadata": {},
        }

        with (
            patch("app.metrics.get_active_trades", return_value=[]),
            patch("app.metrics.get_closed_trades", return_value=[closed_profit, closed_loss, closed_unknown]),
            patch("app.metrics.get_trade_history", return_value=[closed_profit, closed_loss, closed_unknown]),
        ):
            metrics = get_metrics(now=NOW)

        self.assertEqual(metrics["win_trades"], 1)
        self.assertEqual(metrics["loss_trades"], 1)
        self.assertEqual(metrics["known_closed_trades"], 2)
        self.assertEqual(metrics["unknown_closed_trades"], 1)
        self.assertEqual(metrics["win_rate"], 0.5)

    def test_open_partial_realized_is_included_in_bdt_daily_metrics(self) -> None:
        open_partial = {
            "journal_id": "jrnl-open",
            "status": "active",
            "realized_pnl": 22.48,
            "fees": 3.0,
            "exchange_metadata": {
                "partial_close_sync": {
                    "pnl_by_bdt_day": {"2026-07-13": 22.48},
                    "fees_by_bdt_day": {"2026-07-13": 3.0},
                }
            },
        }

        with (
            patch("app.metrics.get_active_trades", return_value=[open_partial]),
            patch("app.metrics.get_closed_trades", return_value=[]),
            patch("app.metrics.get_closed_trade_history", return_value=[]),
            patch("app.metrics.get_trade_history", return_value=[open_partial]),
        ):
            metrics = get_metrics(now=NOW)

        self.assertEqual(metrics["today_realized_pnl"], 22.48)
        self.assertEqual(metrics["today_fees"], 3.0)
        self.assertEqual(metrics["daily_accounting_timezone"], "Asia/Dhaka")

    def test_closed_and_open_partial_realized_are_combined_without_counting_other_days(self) -> None:
        open_partial = {
            "journal_id": "jrnl-open",
            "status": "active",
            "exchange_metadata": {
                "partial_close_sync": {
                    "pnl_by_bdt_day": {"2026-07-12": 99.0, "2026-07-13": 8.0},
                    "fees_by_bdt_day": {"2026-07-12": 9.0, "2026-07-13": 0.8},
                }
            },
        }
        closed_today = {
            "journal_id": "jrnl-closed",
            "status": "closed",
            "closed_at": "2026-07-12T18:30:00+00:00",
            "realized_pnl": -2.5,
            "fees": 0.4,
            "exchange_metadata": {},
        }
        closed_previous_day = {
            "journal_id": "jrnl-old",
            "status": "closed",
            "closed_at": "2026-07-12T10:00:00+00:00",
            "realized_pnl": 100.0,
            "fees": 10.0,
            "exchange_metadata": {},
        }

        with (
            patch("app.metrics.get_active_trades", return_value=[open_partial]),
            patch("app.metrics.get_closed_trades", return_value=[closed_today, closed_previous_day]),
            patch("app.metrics.get_trade_history", return_value=[open_partial, closed_today, closed_previous_day]),
        ):
            metrics = get_metrics(now=NOW)

        self.assertEqual(metrics["today_realized_pnl"], 5.5)
        self.assertEqual(metrics["today_fees"], 1.2)

    def test_open_trade_without_authoritative_day_map_is_not_guessed(self) -> None:
        open_trade = {
            "journal_id": "jrnl-open",
            "status": "active",
            "realized_pnl": 50.0,
            "fees": 5.0,
            "exchange_metadata": {},
        }

        with (
            patch("app.metrics.get_active_trades", return_value=[open_trade]),
            patch("app.metrics.get_closed_trades", return_value=[]),
            patch("app.metrics.get_closed_trade_history", return_value=[]),
            patch("app.metrics.get_trade_history", return_value=[open_trade]),
        ):
            metrics = get_metrics(now=NOW)

        self.assertEqual(metrics["today_realized_pnl"], 0.0)
        self.assertEqual(metrics["today_fees"], 0.0)


if __name__ == "__main__":
    unittest.main()

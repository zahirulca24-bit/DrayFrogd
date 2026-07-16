from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected block not found in {path}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


Path("app/metrics.py").write_text(
    '''from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from app.authoritative_state import get_snapshot
from app.execution import get_closed_trades, get_operator_active_trades
from app.journal import get_closed_trade_history, get_trade_history
from app.ledger_audit import get_account_ledger_audit


BDT = ZoneInfo("Asia/Dhaka")


def get_metrics(
    client: Any | None = None,
    now: datetime | None = None,
    bdt_date: str | None = None,
) -> dict[str, Any]:
    snapshot = get_snapshot()
    active_trades = list(snapshot.get("trades") or []) if int(snapshot.get("version") or 0) > 0 else get_operator_active_trades()
    closed_trades = get_closed_trades() or get_closed_trade_history()
    total_trades = len(active_trades) + len(closed_trades)
    outcomes = [_classify_outcome(trade) for trade in closed_trades]
    win_trades = sum(1 for outcome in outcomes if outcome == "win")
    loss_trades = sum(1 for outcome in outcomes if outcome == "loss")
    known_closed_trades = win_trades + loss_trades
    win_rate = (win_trades / known_closed_trades) if known_closed_trades else 0.0
    pnl_r = (win_trades * 2.0) - loss_trades

    current = now or datetime.now(UTC)
    target_day = bdt_date or current.astimezone(BDT).date().isoformat()
    journal_trades = get_trade_history(limit=1000)
    journal_realized, journal_fees, journal_evidence_count = _today_financials(journal_trades, current)
    truth = _daily_financial_truth(
        client=client,
        target_day=target_day,
        journal_realized=journal_realized,
        journal_fees=journal_fees,
        journal_evidence_count=journal_evidence_count,
    )

    return {
        "total_trades": total_trades,
        "active_trades_count": len(active_trades),
        "closed_trades_count": len(closed_trades),
        "win_trades": win_trades,
        "loss_trades": loss_trades,
        "known_closed_trades": known_closed_trades,
        "unknown_closed_trades": max(len(closed_trades) - known_closed_trades, 0),
        "win_rate": round(win_rate, 4),
        "pnl_r": round(pnl_r, 4),
        **truth,
        "daily_accounting_timezone": "Asia/Dhaka",
    }


def get_portfolio_summary(client: Any | None = None) -> dict[str, Any]:
    metrics = get_metrics(client)
    return {
        "active_trades": metrics["active_trades_count"],
        "closed_trades": metrics["closed_trades_count"],
        "total_trades": metrics["total_trades"],
        "win_rate": metrics["win_rate"],
        "pnl_r": metrics["pnl_r"],
        "today_realized_pnl": metrics["today_realized_pnl"],
        "today_account_net_pnl": metrics["today_account_net_pnl"],
        "today_trade_net_pnl": metrics["today_trade_net_pnl"],
        "today_fees": metrics["today_fees"],
        "today_funding": metrics["today_funding"],
        "today_financial_status": metrics["today_financial_status"],
        "today_financial_source": metrics["today_financial_source"],
        "execution_mode": str(get_snapshot().get("mode") or next((trade.get("execution_mode") for trade in get_operator_active_trades() if trade.get("execution_mode")), "demo")),
    }


def _daily_financial_truth(
    *,
    client: Any | None,
    target_day: str,
    journal_realized: float,
    journal_fees: float,
    journal_evidence_count: int,
) -> dict[str, Any]:
    if client is not None:
        try:
            audit = get_account_ledger_audit(client, bdt_date=target_day, limit=100)
        except Exception as exc:
            audit = {"ok": False, "error": str(exc), "summary": {}}

        if audit.get("ok"):
            summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
            account_net = _number(summary.get("net_change")) or 0.0
            trade_net = _number(summary.get("trade_change")) or 0.0
            fees = abs(_number(summary.get("fees")) or 0.0)
            funding = _number(summary.get("funding")) or 0.0
            reconciliation_gap = account_net - journal_realized
            return {
                "today_realized_pnl": round(account_net, 8),
                "today_account_net_pnl": round(account_net, 8),
                "today_trade_net_pnl": round(trade_net, 8),
                "today_fees": round(fees, 8),
                "today_funding": round(funding, 8),
                "today_financial_date": str(audit.get("date") or target_day),
                "today_financial_status": "authoritative",
                "today_financial_source": "bybit_transaction_log",
                "financial_truth_error": None,
                "journal_today_realized_pnl": round(journal_realized, 8),
                "journal_today_fees": round(journal_fees, 8),
                "reconciliation_gap": round(reconciliation_gap, 8),
                "ledger_record_count": int(summary.get("record_count") or 0),
            }

        ledger_error = str(audit.get("error") or "Bybit transaction log unavailable")
    else:
        ledger_error = "Exchange client unavailable"

    status = "fallback" if journal_evidence_count > 0 else "unavailable"
    source = "journal_fallback" if journal_evidence_count > 0 else "unavailable"
    return {
        "today_realized_pnl": round(journal_realized, 8),
        "today_account_net_pnl": round(journal_realized, 8),
        "today_trade_net_pnl": round(journal_realized, 8),
        "today_fees": round(journal_fees, 8),
        "today_funding": 0.0,
        "today_financial_date": target_day,
        "today_financial_status": status,
        "today_financial_source": source,
        "financial_truth_error": ledger_error,
        "journal_today_realized_pnl": round(journal_realized, 8),
        "journal_today_fees": round(journal_fees, 8),
        "reconciliation_gap": None,
        "ledger_record_count": 0,
    }


def _today_financials(trades: list[dict[str, Any]], now: datetime) -> tuple[float, float, int]:
    today = now.astimezone(BDT).date().isoformat()
    realized = 0.0
    fees = 0.0
    evidence_count = 0

    for trade in trades:
        status = str(trade.get("status") or "").lower()
        metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
        partial = metadata.get("partial_close_sync") if isinstance(metadata.get("partial_close_sync"), dict) else {}
        if not partial:
            partial = metadata.get("risk_realized_progress") if isinstance(metadata.get("risk_realized_progress"), dict) else {}

        if status != "closed":
            pnl_by_day = partial.get("pnl_by_bdt_day") if isinstance(partial.get("pnl_by_bdt_day"), dict) else {}
            fees_by_day = partial.get("fees_by_bdt_day") if isinstance(partial.get("fees_by_bdt_day"), dict) else {}
            if today in pnl_by_day or today in fees_by_day:
                evidence_count += 1
            realized += _number(pnl_by_day.get(today)) or 0.0
            fees += abs(_number(fees_by_day.get(today)) or 0.0)
            continue

        closed_at = _parse_time(trade.get("closed_at"))
        if closed_at is None or closed_at.astimezone(BDT).date().isoformat() != today:
            continue
        evidence_count += 1
        realized += _number(trade.get("realized_pnl")) or 0.0
        fees += abs(_number(trade.get("fees")) or 0.0)

    return realized, fees, evidence_count


def _classify_outcome(trade: dict[str, Any]) -> str:
    realized_pnl = _number(trade.get("realized_pnl"))
    if realized_pnl is not None:
        if realized_pnl > 0:
            return "win"
        if realized_pnl < 0:
            return "loss"
        return "flat"

    result = str(trade.get("result") or "").lower().strip()
    if result in {"tp", "profit", "win", "take_profit"}:
        return "win"
    if result in {"sl", "loss", "stop_loss"}:
        return "loss"
    if result in {"flat", "breakeven", "break_even"}:
        return "flat"
    return "unknown"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None
''',
    encoding="utf-8",
)

replace_once(
    "app/main.py",
    '''@app.get("/metrics")
def metrics(_: dict = Depends(require_authenticated)) -> dict:
    return get_metrics()


@app.get("/portfolio")
def portfolio(_: dict = Depends(require_authenticated)) -> dict:
    return get_portfolio_summary()
''',
    '''@app.get("/metrics")
def metrics(_: dict = Depends(require_authenticated)) -> dict:
    client = get_exchange_client(get_execution_mode())
    try:
        repair_incomplete_journal_closes(client)
    except Exception:
        pass
    return get_metrics(client)


@app.get("/portfolio")
def portfolio(_: dict = Depends(require_authenticated)) -> dict:
    client = get_exchange_client(get_execution_mode())
    try:
        repair_incomplete_journal_closes(client)
    except Exception:
        pass
    return get_portfolio_summary(client)
''',
)

replace_once(
    "frontend/src/types.ts",
    '''export interface MetricsResponse {
  total_trades: number;
  active_trades_count: number;
  closed_trades_count: number;
  win_trades: number;
  loss_trades: number;
  win_rate: number;
  pnl_r: number;
}
''',
    '''export interface MetricsResponse {
  total_trades: number;
  active_trades_count: number;
  closed_trades_count: number;
  win_trades: number;
  loss_trades: number;
  win_rate: number;
  pnl_r: number;
  today_realized_pnl: number;
  today_account_net_pnl: number;
  today_trade_net_pnl: number;
  today_fees: number;
  today_funding: number;
  today_financial_date: string;
  today_financial_status: "authoritative" | "fallback" | "unavailable";
  today_financial_source: "bybit_transaction_log" | "journal_fallback" | "unavailable";
  financial_truth_error: string | null;
  journal_today_realized_pnl: number;
  journal_today_fees: number;
  reconciliation_gap: number | null;
  ledger_record_count: number;
  daily_accounting_timezone: string;
}
''',
)

replace_once(
    "frontend/src/App.tsx",
    '''const emptyMetrics: MetricsResponse = {
  total_trades: 0,
  active_trades_count: 0,
  closed_trades_count: 0,
  win_trades: 0,
  loss_trades: 0,
  win_rate: 0,
  pnl_r: 0,
};
''',
    '''const emptyMetrics: MetricsResponse = {
  total_trades: 0,
  active_trades_count: 0,
  closed_trades_count: 0,
  win_trades: 0,
  loss_trades: 0,
  win_rate: 0,
  pnl_r: 0,
  today_realized_pnl: 0,
  today_account_net_pnl: 0,
  today_trade_net_pnl: 0,
  today_fees: 0,
  today_funding: 0,
  today_financial_date: "",
  today_financial_status: "unavailable",
  today_financial_source: "unavailable",
  financial_truth_error: null,
  journal_today_realized_pnl: 0,
  journal_today_fees: 0,
  reconciliation_gap: null,
  ledger_record_count: 0,
  daily_accounting_timezone: "Asia/Dhaka",
};
''',
)
replace_once(
    "frontend/src/App.tsx",
    '''            account={account}
            activeTrades={activeTrades}
''',
    '''            account={account}
            metrics={metrics}
            activeTrades={activeTrades}
''',
)
replace_once(
    "frontend/src/App.tsx",
    '''          <PerformanceStrategy
            authToken={authToken}
            history={tradeHistory}
          />
''',
    '''          <PerformanceStrategy
            authToken={authToken}
            history={tradeHistory}
            metrics={metrics}
          />
''',
)

replace_once(
    "frontend/src/components/DashboardView.tsx",
    '''  MarketTicker,
  SystemReadiness,
''',
    '''  MarketTicker,
  MetricsResponse,
  SystemReadiness,
''',
)
replace_once(
    "frontend/src/components/DashboardView.tsx",
    '''  account: AccountResponse;
  activeTrades: Trade[];
''',
    '''  account: AccountResponse;
  metrics: MetricsResponse;
  activeTrades: Trade[];
''',
)
replace_once(
    "frontend/src/components/DashboardView.tsx",
    '''function formatMoney(value: number) {
  const sign = value < 0 ? "-" : "";
''',
    '''function formatMoney(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "N/A";
  const sign = value < 0 ? "-" : "";
''',
)
replace_once(
    "frontend/src/components/DashboardView.tsx",
    '''  account,
  activeTrades,
''',
    '''  account,
  metrics,
  activeTrades,
''',
)
replace_once(
    "frontend/src/components/DashboardView.tsx",
    '''  const unrealizedPnl = resolveUnrealizedPnl(wallet, account, activeTrades);
  const exposure = resolveExposure(account, activeTrades);
  const [reportedRealizedPnl, setReportedRealizedPnl] = useState<number | null>(null);

  const closedOnlyTodayRealizedPnl = useMemo(
    () =>
      tradeHistory
        .filter((trade) => isTodayInBdt(trade.closedAt))
        .reduce((sum, trade) => sum + numberValue(trade.pnl), 0),
    [tradeHistory],
  );
  const todayRealizedPnl = reportedRealizedPnl ?? closedOnlyTodayRealizedPnl;
  const todayNetPnl = todayRealizedPnl + unrealizedPnl;
''',
    '''  const unrealizedPnl = resolveUnrealizedPnl(wallet, account, activeTrades);
  const exposure = resolveExposure(account, activeTrades);
  const financialTruthAvailable = metrics.today_financial_status !== "unavailable";
  const todayAccountNetPnl = financialTruthAvailable ? numberValue(metrics.today_account_net_pnl) : null;
  const todayTotalPnl = todayAccountNetPnl === null ? null : todayAccountNetPnl + unrealizedPnl;
''',
)
replace_once(
    "frontend/src/components/DashboardView.tsx",
    '''  useEffect(() => {
    if (!authToken) return;
    let cancelled = false;

    const loadDailyFinancials = async () => {
      try {
        const response = (await api.getMetrics(authToken)) as { today_realized_pnl?: number };
        const value = Number(response.today_realized_pnl);
        if (!cancelled) setReportedRealizedPnl(Number.isFinite(value) ? value : null);
      } catch {
        if (!cancelled) setReportedRealizedPnl(null);
      }
    };

    void loadDailyFinancials();
    const interval = setInterval(loadDailyFinancials, 10_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken, activeTrades.length, tradeHistory.length]);

''',
    '''''',
)
replace_once(
    "frontend/src/components/DashboardView.tsx",
    '''        <KpiCard label="Today's Realized" value={formatMoney(todayRealizedPnl)} icon={todayRealizedPnl >= 0 ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />} tone={todayRealizedPnl >= 0 ? "good" : "bad"} helper="Closed trades + open partial fills today" />
        <KpiCard label="Unrealized" value={formatMoney(unrealizedPnl)} icon={<Layers3 className="h-4 w-4" />} tone={unrealizedPnl >= 0 ? "good" : "bad"} helper="Open-position PnL" />
        <KpiCard label="Today's Net" value={formatMoney(todayNetPnl)} icon={<Zap className="h-4 w-4" />} tone={todayNetPnl >= 0 ? "good" : "bad"} helper="Realized + unrealized" />
''',
    '''        <KpiCard label="Today's Account Net" value={formatMoney(todayAccountNetPnl)} icon={(todayAccountNetPnl ?? 0) >= 0 ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />} tone={todayAccountNetPnl === null ? "muted" : todayAccountNetPnl >= 0 ? "good" : "bad"} helper={metrics.today_financial_status === "authoritative" ? `Bybit ledger · fees ${formatMoney(metrics.today_fees)}` : metrics.today_financial_status === "fallback" ? "Journal fallback" : "Financial truth unavailable"} />
        <KpiCard label="Unrealized" value={formatMoney(unrealizedPnl)} icon={<Layers3 className="h-4 w-4" />} tone={unrealizedPnl >= 0 ? "good" : "bad"} helper="Open-position PnL" />
        <KpiCard label="Today's Total" value={formatMoney(todayTotalPnl)} icon={<Zap className="h-4 w-4" />} tone={todayTotalPnl === null ? "muted" : todayTotalPnl >= 0 ? "good" : "bad"} helper="Account net + unrealized" />
''',
)

replace_once(
    "frontend/src/components/PerformanceStrategy.tsx",
    '''import { JournalTradeEntry, StrategyAuditResponse, TradeHistoryEntry } from "../types";
''',
    '''import { JournalTradeEntry, MetricsResponse, StrategyAuditResponse, TradeHistoryEntry } from "../types";
''',
)
replace_once(
    "frontend/src/components/PerformanceStrategy.tsx",
    '''interface PerformanceStrategyProps {
  authToken: string | null;
  history: TradeHistoryEntry[];
}
''',
    '''interface PerformanceStrategyProps {
  authToken: string | null;
  history: TradeHistoryEntry[];
  metrics: MetricsResponse;
}
''',
)
replace_once(
    "frontend/src/components/PerformanceStrategy.tsx",
    '''export default function PerformanceStrategy({ authToken, history }: PerformanceStrategyProps) {
''',
    '''export default function PerformanceStrategy({ authToken, history, metrics }: PerformanceStrategyProps) {
''',
)
replace_once(
    "frontend/src/components/PerformanceStrategy.tsx",
    '''  const auditStrategies = strategyAudit?.ok ? strategyAudit.strategies : [];
''',
    '''  const accountNetPnl = metrics.today_financial_status === "unavailable" ? null : metrics.today_account_net_pnl;
  const auditStrategies = strategyAudit?.ok ? strategyAudit.strategies : [];
''',
)
replace_once(
    "frontend/src/components/PerformanceStrategy.tsx",
    '''            <p className="text-xs text-slate-500 mt-1">Real persisted journal data. Open trades populate counts/breakdowns; realized PnL cards use closed trades only.</p>
''',
    '''            <p className="text-xs text-slate-500 mt-1">Account-level Net PnL uses the same Bybit transaction-log truth as Journal and Dashboard. Strategy metrics remain ledger-matched trade analytics.</p>
''',
)
replace_once(
    "frontend/src/components/PerformanceStrategy.tsx",
    '''        <KpiCard label="Net PnL" value={netPnl !== null ? formatMoney(netPnl) : "Insufficient Data"} />
        <KpiCard label="Profit Factor" value={profitFactor === Infinity ? "Infinity" : profitFactor !== null ? profitFactor.toFixed(2) : "Insufficient Data"} />
''',
    '''        <KpiCard label="Account Net (Bybit)" value={accountNetPnl !== null ? formatMoney(accountNetPnl) : "N/A"} />
        <KpiCard label="Strategy Net (Matched)" value={netPnl !== null ? formatMoney(netPnl) : "Insufficient Data"} />
        <KpiCard label="Profit Factor" value={profitFactor === Infinity ? "Infinity" : profitFactor !== null ? profitFactor.toFixed(2) : "Insufficient Data"} />
''',
)

replace_once(
    "frontend/src/components/TradeHistory.tsx",
    '''          <LedgerMetric label="Net Change" value={formatMoney(netChange)} tone={netChange === null ? "neutral" : netChange >= 0 ? "good" : "bad"} />
          <LedgerMetric label="Trade Change" value={formatMoney(summary?.trade_change ?? null)} />
''',
    '''          <LedgerMetric label="Account Net (Bybit)" value={formatMoney(netChange)} tone={netChange === null ? "neutral" : netChange >= 0 ? "good" : "bad"} />
          <LedgerMetric label="Trade Net (Bybit)" value={formatMoney(summary?.trade_change ?? null)} />
''',
)

Path("tests/test_financial_truth_metrics.py").write_text(
    '''import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.metrics import get_metrics


class FakeLedgerClient:
    def __init__(self, *, ok=True):
        self.ok = ok

    def safe_fetch_transaction_log(self, *, start_time, end_time, limit):
        if not self.ok:
            return False, [], "ledger unavailable"
        return True, [
            {
                "transactionTime": str(int(datetime(2026, 7, 16, 12, 0, tzinfo=UTC).timestamp() * 1000)),
                "symbol": "ONDOUSDT",
                "type": "Trade",
                "side": "Sell",
                "fee": "0.5",
                "cashFlow": "12.0",
                "change": "11.5",
                "cashBalance": "944.0",
            },
            {
                "transactionTime": str(int(datetime(2026, 7, 16, 12, 5, tzinfo=UTC).timestamp() * 1000)),
                "symbol": "",
                "type": "Funding Rate Settlement",
                "funding": "0.25",
                "change": "0.25",
                "cashBalance": "944.25",
            },
        ], None


class FinancialTruthMetricsTests(unittest.TestCase):
    @patch("app.metrics.get_trade_history", return_value=[])
    @patch("app.metrics.get_closed_trade_history", return_value=[])
    @patch("app.metrics.get_closed_trades", return_value=[])
    @patch("app.metrics.get_operator_active_trades", return_value=[])
    @patch("app.metrics.get_snapshot", return_value={"version": 0, "trades": [], "mode": "demo"})
    def test_bybit_ledger_is_authoritative_daily_truth(self, *_mocks):
        result = get_metrics(
            FakeLedgerClient(),
            now=datetime(2026, 7, 16, 13, 0, tzinfo=UTC),
            bdt_date="2026-07-16",
        )

        self.assertEqual(result["today_financial_status"], "authoritative")
        self.assertEqual(result["today_financial_source"], "bybit_transaction_log")
        self.assertAlmostEqual(result["today_account_net_pnl"], 11.75)
        self.assertAlmostEqual(result["today_trade_net_pnl"], 11.5)
        self.assertAlmostEqual(result["today_fees"], 0.5)
        self.assertAlmostEqual(result["today_funding"], 0.25)
        self.assertEqual(result["ledger_record_count"], 2)

    @patch("app.metrics.get_trade_history", return_value=[])
    @patch("app.metrics.get_closed_trade_history", return_value=[])
    @patch("app.metrics.get_closed_trades", return_value=[])
    @patch("app.metrics.get_operator_active_trades", return_value=[])
    @patch("app.metrics.get_snapshot", return_value={"version": 0, "trades": [], "mode": "demo"})
    def test_unavailable_ledger_is_not_claimed_as_authoritative_zero(self, *_mocks):
        result = get_metrics(
            FakeLedgerClient(ok=False),
            now=datetime(2026, 7, 16, 13, 0, tzinfo=UTC),
            bdt_date="2026-07-16",
        )

        self.assertEqual(result["today_financial_status"], "unavailable")
        self.assertEqual(result["today_financial_source"], "unavailable")
        self.assertEqual(result["today_account_net_pnl"], 0.0)
        self.assertIn("ledger unavailable", result["financial_truth_error"])

    @patch("app.metrics.get_trade_history")
    @patch("app.metrics.get_closed_trade_history", return_value=[])
    @patch("app.metrics.get_closed_trades", return_value=[])
    @patch("app.metrics.get_operator_active_trades", return_value=[])
    @patch("app.metrics.get_snapshot", return_value={"version": 0, "trades": [], "mode": "demo"})
    def test_journal_fallback_is_explicit_when_ledger_fails(self, _snapshot, _active, _closed, _closed_history, trade_history):
        trade_history.return_value = [
            {
                "status": "closed",
                "closed_at": "2026-07-16T12:00:00+00:00",
                "realized_pnl": "5.25",
                "fees": "0.75",
            }
        ]
        result = get_metrics(
            FakeLedgerClient(ok=False),
            now=datetime(2026, 7, 16, 13, 0, tzinfo=UTC),
            bdt_date="2026-07-16",
        )

        self.assertEqual(result["today_financial_status"], "fallback")
        self.assertEqual(result["today_financial_source"], "journal_fallback")
        self.assertAlmostEqual(result["today_account_net_pnl"], 5.25)
        self.assertAlmostEqual(result["today_fees"], 0.75)


if __name__ == "__main__":
    unittest.main()
''',
    encoding="utf-8",
)

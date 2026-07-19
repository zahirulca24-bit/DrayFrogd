import type { ReactNode } from "react";
import { AccountResponse, MetricsResponse, PortfolioSummary, Trade, TradeHistoryEntry } from "../types";
import { Wallet, RefreshCw, Layers, TrendingUp, AlertTriangle } from "lucide-react";


interface PortfolioProps {
  account: AccountResponse;
  metrics: MetricsResponse;
  portfolio: PortfolioSummary;
  activeTrades: Trade[];
  tradeHistory: TradeHistoryEntry[];
  loading: boolean;
  onRefresh: () => Promise<void>;
}


function numeric(value: string | number | undefined) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}


export default function Portfolio({
  account,
  metrics,
  portfolio,
  activeTrades,
  tradeHistory,
  loading,
  onRefresh,
}: PortfolioProps) {
  const wallet = account.wallet.data || {};
  const equity = numeric(wallet.totalEquity || wallet.totalWalletBalance);
  const totalBalance = numeric(wallet.totalWalletBalance || wallet.totalEquity);
  const availableBalance = numeric(wallet.totalAvailableBalance);
  const usedMargin = Math.max(totalBalance - availableBalance, 0);

  return (
    <div className="space-y-6" id="portfolio-root">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4" id="portfolio-header-grid">
        <MetricCard label="Total Equity" value={equity} icon={<Wallet className="w-4 h-4 text-emerald-400" />} />
        <MetricCard label="Wallet Balance" value={totalBalance} icon={<Wallet className="w-4 h-4 text-rose-500" />} />
        <MetricCard label="Available Balance" value={availableBalance} icon={<Layers className="w-4 h-4 text-violet-400" />} />
        <MetricCard label="Used Margin" value={usedMargin} icon={<AlertTriangle className="w-4 h-4 text-amber-500" />} />
        <MetricCard label="Win Rate" value={metrics.win_rate * 100} suffix="%" icon={<TrendingUp className="w-4 h-4 text-emerald-400" />} />
        <MetricCard label="PnL" value={metrics.pnl_r} suffix="R" icon={<TrendingUp className={`w-4 h-4 ${metrics.pnl_r >= 0 ? "text-emerald-400" : "text-rose-500"}`} />} />
      </div>

      <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md bento-card-glow" id="portfolio-assets-section">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="text-sm font-semibold text-white tracking-tight font-sans">Portfolio Summary</h3>
            <p className="text-xs text-slate-500 mt-0.5">Backend portfolio and active trade snapshot</p>
          </div>
          <button
            id="refresh-portfolio-btn"
            onClick={onRefresh}
            disabled={loading}
            className="p-2 hover:bg-slate-800/40 text-slate-400 hover:text-slate-200 rounded-xl transition-all border border-slate-800 cursor-pointer disabled:opacity-50"
            title="Refresh portfolio summary"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-5 gap-3 mb-6">
          <SummaryPill label="Total Trades" value={portfolio.total_trades} />
          <SummaryPill label="Active" value={portfolio.active_trades} />
          <SummaryPill label="Closed" value={portfolio.closed_trades} />
          <SummaryPill label="Wins" value={metrics.win_trades} />
          <SummaryPill label="Losses" value={metrics.loss_trades} />
        </div>

        <div className="mb-6 grid grid-cols-1 md:grid-cols-3 gap-3">
          <SummaryPill label="Mode" valueText={(portfolio.execution_mode || account.mode || null)?.toUpperCase() || "N/A"} />
          <SummaryPill label="SL Losses With Reason" value={tradeHistory.filter((trade) => trade.result === "LOSS" && trade.reason).length} />
          <SummaryPill label="History Entries" value={tradeHistory.length} />
        </div>

        <div className="overflow-x-auto" id="portfolio-table-wrapper">
          <table className="w-full text-left border-collapse" id="portfolio-table">
            <thead>
              <tr className="border-b border-slate-800 text-[10px] font-mono uppercase tracking-wider text-slate-500">
                <th className="py-3 px-4 font-semibold">Pair</th>
                <th className="py-3 px-4 font-semibold">Direction</th>
                <th className="py-3 px-4 font-semibold text-right">Entry</th>
                <th className="py-3 px-4 font-semibold text-right">Stop Loss</th>
                <th className="py-3 px-4 font-semibold text-right">Take Profit</th>
                <th className="py-3 px-4 font-semibold text-right">Quantity</th>
                <th className="py-3 px-4 font-semibold text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/30 text-sm font-sans text-slate-300">
              {activeTrades.map((trade) => (
                <tr key={trade.id} className="hover:bg-slate-900/10 transition-colors">
                  <td className="py-4 px-4 font-semibold text-white">{trade.pair}</td>
                  <td className={`py-4 px-4 font-bold ${trade.direction === "LONG" ? "text-emerald-400" : "text-rose-400"}`}>{trade.direction}</td>
                  <td className="py-4 px-4 font-mono text-xs text-right">${trade.entryPrice.toFixed(4)}</td>
                  <td className="py-4 px-4 font-mono text-xs text-right">${trade.stopLoss.toFixed(4)}</td>
                  <td className="py-4 px-4 font-mono text-xs text-right">${trade.takeProfit.toFixed(4)}</td>
                  <td className="py-4 px-4 font-mono text-xs text-right">{trade.size}</td>
                  <td className="py-4 px-4 font-mono text-xs text-right text-slate-400">{trade.rawStatus || trade.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {activeTrades.length === 0 && (
          <div className="py-8 text-center text-slate-500 font-mono text-xs">No active trades returned by the backend.</div>
        )}
      </div>
    </div>
  );
}


function MetricCard({
  label,
  value,
  icon,
  suffix = "",
}: {
  label: string;
  value: number;
  icon: ReactNode;
  suffix?: string;
}) {
  return (
    <div className="bg-bento-card border border-slate-800 rounded-2xl p-5 bento-card-glow shadow-md">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-slate-400 font-mono uppercase tracking-wider font-semibold">{label}</span>
        {icon}
      </div>
      <h2 className="text-xl font-bold text-white tracking-tight font-sans">
        {suffix === "%" ? `${value.toFixed(2)}%` : suffix === "R" ? `${value.toFixed(2)}R` : `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
      </h2>
    </div>
  );
}


function SummaryPill({ label, value, valueText }: { label: string; value?: number; valueText?: string }) {
  return (
    <div className="bg-[#0A0B0E] border border-slate-800 rounded-xl p-4 text-center">
      <div className="text-[10px] text-slate-500 font-mono uppercase mb-1">{label}</div>
      <div className="text-xl font-bold text-white">{valueText ?? value ?? 0}</div>
    </div>
  );
}

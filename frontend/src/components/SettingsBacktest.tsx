import { useState } from "react";
import { Activity, BarChart3, Play, ShieldAlert } from "lucide-react";
import { api } from "../api";
import type { BacktestResponse, BacktestTrade } from "../types";

interface SettingsBacktestProps {
  authToken: string | null;
}

const STRATEGIES = [
  { label: "All strategy pipeline", value: "all" },
  { label: "EMA pullback", value: "ema_pullback" },
  { label: "Breakout", value: "breakout" },
  { label: "Pure SMC", value: "pure_smc" },
];

function money(value?: number | null) {
  return Number.isFinite(Number(value)) ? `$${Number(value).toFixed(2)}` : "N/A";
}

function number(value?: number | null, suffix = "") {
  return Number.isFinite(Number(value)) ? `${Number(value).toFixed(2)}${suffix}` : "N/A";
}

function time(value?: string | null) {
  if (!value) return "N/A";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "N/A" : parsed.toLocaleString("en-BD", { timeZone: "Asia/Dhaka" });
}

export default function SettingsBacktest({ authToken }: SettingsBacktestProps) {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [strategy, setStrategy] = useState("all");
  const [candleLimit, setCandleLimit] = useState("1000");
  const [riskAmount, setRiskAmount] = useState("20");
  const [feeBps, setFeeBps] = useState("5.5");
  const [minRr, setMinRr] = useState("1.5");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResponse | null>(null);

  const runBacktest = async () => {
    if (!authToken) {
      setError("Session expired. Please log in again.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await api.runBacktest(authToken, {
        symbol: symbol.trim().toUpperCase(),
        strategy,
        candle_limit: Number(candleLimit),
        risk_amount: Number(riskAmount),
        fee_bps: Number(feeBps),
        min_risk_reward: Number(minRr),
      });
      if (!response.ok) {
        setError(response.error || "Backtest failed.");
      }
      setResult(response);
    } catch (err: any) {
      setError(err?.message || "Backtest failed.");
    } finally {
      setLoading(false);
    }
  };

  const summary = result?.summary;
  const trades = result?.trades || [];

  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-slate-800 bg-bento-card p-6 shadow-md">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <div className="rounded-xl border border-sky-500/20 bg-sky-500/10 p-2.5 text-sky-300">
                <BarChart3 className="h-5 w-5" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-white">Strategy Backtest Engine</h1>
                <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500">
                  Replays current strategy logic on recent Bybit 1m/5m candles. This is research-only: no order is submitted.
                </p>
              </div>
            </div>
            <div className="mt-4 rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs leading-5 text-amber-200">
              Conservative rule: if stop-loss and take-profit both touch inside one candle, the test counts stop-loss first.
            </div>
          </div>
          <button
            type="button"
            onClick={() => void runBacktest()}
            disabled={loading}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-5 py-3 text-xs font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            {loading ? "RUNNING..." : "RUN BACKTEST"}
          </button>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <BacktestInput label="Symbol" value={symbol} onChange={setSymbol} />
          <label className="space-y-2">
            <span className="text-[10px] font-mono uppercase tracking-wider text-slate-500">Strategy</span>
            <select value={strategy} onChange={(event) => setStrategy(event.target.value)} className="dashboard-input">
              {STRATEGIES.map((item) => (
                <option key={item.value} value={item.value}>{item.label}</option>
              ))}
            </select>
          </label>
          <BacktestInput label="1m Candles" value={candleLimit} onChange={setCandleLimit} type="number" />
          <BacktestInput label="Risk USDT" value={riskAmount} onChange={setRiskAmount} type="number" />
          <BacktestInput label="Fee bps/side" value={feeBps} onChange={setFeeBps} type="number" />
          <BacktestInput label="Min RR" value={minRr} onChange={setMinRr} type="number" />
        </div>
      </section>

      {error && (
        <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-200">
          {error}
        </div>
      )}

      {summary && (
        <section className="grid grid-cols-2 gap-3 xl:grid-cols-8">
          <Stat label="Trades" value={String(summary.trades)} />
          <Stat label="Win Rate" value={number(summary.win_rate, "%")} />
          <Stat label="Net PnL" value={money(summary.net_pnl)} tone={summary.net_pnl >= 0 ? "good" : "bad"} />
          <Stat label="PnL R" value={number(summary.pnl_r, "R")} tone={summary.pnl_r >= 0 ? "good" : "bad"} />
          <Stat label="Profit Factor" value={summary.profit_factor === null ? "N/A" : number(summary.profit_factor)} />
          <Stat label="Max DD" value={money(summary.max_drawdown)} tone="bad" />
          <Stat label="Skipped" value={String(summary.skipped_signals)} />
          <Stat label="Candles" value={`${result?.candles_1m || 0} / ${result?.candles_5m || 0}`} />
        </section>
      )}

      <section className="rounded-2xl border border-slate-800 bg-bento-card p-5 shadow-md">
        <div className="mb-4 flex items-center gap-2">
          <Activity className="h-4 w-4 text-emerald-300" />
          <h2 className="text-sm font-semibold text-white">Backtest Trades</h2>
        </div>
        {trades.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-left text-xs">
              <thead className="border-b border-slate-800 text-[10px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-3 py-3">Time</th>
                  <th className="px-3 py-3">Strategy</th>
                  <th className="px-3 py-3">Side</th>
                  <th className="px-3 py-3">Entry</th>
                  <th className="px-3 py-3">SL</th>
                  <th className="px-3 py-3">TP</th>
                  <th className="px-3 py-3">Result</th>
                  <th className="px-3 py-3">Fees</th>
                  <th className="px-3 py-3 text-right">Net</th>
                </tr>
              </thead>
              <tbody>
                {trades.slice().reverse().map((trade, index) => <TradeRow key={`${trade.opened_at}-${index}`} trade={trade} />)}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-slate-800 bg-[#0A0B0E] px-6 py-12 text-center text-xs text-slate-500">
            <ShieldAlert className="mx-auto mb-3 h-5 w-5 text-slate-600" />
            Run a backtest to inspect simulated trades.
          </div>
        )}
      </section>
    </div>
  );
}

function BacktestInput({ label, value, onChange, type = "text" }: { label: string; value: string; onChange: (value: string) => void; type?: string }) {
  return (
    <label className="space-y-2">
      <span className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</span>
      <input type={type} value={value} onChange={(event) => onChange(event.target.value)} className="dashboard-input" />
    </label>
  );
}

function Stat({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "good" | "bad" | "neutral" }) {
  const toneClass = tone === "good" ? "text-emerald-300" : tone === "bad" ? "text-rose-300" : "text-white";
  return (
    <div className="rounded-2xl border border-slate-800 bg-bento-card p-4 shadow-md">
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-2 text-lg font-bold ${toneClass}`}>{value}</div>
    </div>
  );
}

function TradeRow({ trade }: { trade: BacktestTrade }) {
  const won = trade.result === "win";
  return (
    <tr className="border-b border-slate-900 text-slate-300">
      <td className="px-3 py-3 font-mono text-[10px] text-slate-500">{time(trade.opened_at)}</td>
      <td className="px-3 py-3 text-white">{trade.strategy}</td>
      <td className={won ? "px-3 py-3 text-emerald-300" : "px-3 py-3 text-rose-300"}>{trade.direction.toUpperCase()}</td>
      <td className="px-3 py-3 font-mono">${trade.entry}</td>
      <td className="px-3 py-3 font-mono text-rose-300">${trade.stop_loss}</td>
      <td className="px-3 py-3 font-mono text-emerald-300">${trade.take_profit}</td>
      <td className={won ? "px-3 py-3 font-semibold text-emerald-300" : "px-3 py-3 font-semibold text-rose-300"}>{trade.result.toUpperCase()}</td>
      <td className="px-3 py-3 font-mono text-amber-300">{money(trade.fees)}</td>
      <td className={trade.net_pnl >= 0 ? "px-3 py-3 text-right font-mono text-emerald-300" : "px-3 py-3 text-right font-mono text-rose-300"}>{money(trade.net_pnl)}</td>
    </tr>
  );
}

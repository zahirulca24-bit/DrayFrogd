from pathlib import Path

path = Path("scripts/apply_p0_financial_truth.py")
text = path.read_text(encoding="utf-8")
text = text.replace('tone={todayAccountNetPnl === null ? "muted" : todayAccountNetPnl >= 0 ? "good" : "bad"}', 'tone={todayAccountNetPnl === null ? "neutral" : todayAccountNetPnl >= 0 ? "good" : "bad"}')
text = text.replace('tone={todayTotalPnl === null ? "muted" : todayTotalPnl >= 0 ? "good" : "bad"}', 'tone={todayTotalPnl === null ? "neutral" : todayTotalPnl >= 0 ? "good" : "bad"}')

needle = '''replace_once(
    "frontend/src/components/DashboardView.tsx",
    ''' + "'''" + '''  account: AccountResponse;\n  metrics: MetricsResponse;\n  activeTrades: Trade[];\n''' + "'''" + ''',
    ''' + "'''" + '''  account: AccountResponse;\n  metrics: MetricsResponse;\n  activeTrades: Trade[];\n''' + "'''" + ''',
)\n'''
# Add cleanup replacements immediately before the performance component edits.
marker = '''replace_once(
    "frontend/src/components/PerformanceStrategy.tsx",
'''
cleanup = '''replace_once(
    "frontend/src/components/DashboardView.tsx",
    ''' + "'''" + '''  Trade,\n  TradeHistoryEntry,\n} from "../types";\n''' + "'''" + ''',
    ''' + "'''" + '''  Trade,\n} from "../types";\n''' + "'''" + ''',
)
replace_once(
    "frontend/src/components/DashboardView.tsx",
    ''' + "'''" + '''  tradeHistory: TradeHistoryEntry[];\n''' + "'''" + ''',
    ''' + "'''" + '''''' + "'''" + ''',
)
replace_once(
    "frontend/src/components/DashboardView.tsx",
    ''' + "'''" + '''  tradeHistory,\n''' + "'''" + ''',
    ''' + "'''" + '''''' + "'''" + ''',
)
replace_once(
    "frontend/src/components/DashboardView.tsx",
    ''' + "'''" + '''function isTodayInBdt(value?: string | null) {\n  if (!value) return false;\n  const parsed = new Date(value);\n  if (Number.isNaN(parsed.getTime())) return false;\n  const itemDay = parsed.toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" });\n  const currentDay = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" });\n  return itemDay === currentDay;\n}\n\n''' + "'''" + ''',
    ''' + "'''" + '''''' + "'''" + ''',
)
replace_once(
    "frontend/src/App.tsx",
    ''' + "'''" + '''            tradeHistory={tradeHistory}\n''' + "'''" + ''',
    ''' + "'''" + '''''' + "'''" + ''',
)

'''
if marker not in text:
    raise SystemExit("performance marker not found")
text = text.replace(marker, cleanup + marker, 1)
path.write_text(text, encoding="utf-8")

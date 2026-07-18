import { api } from "./api";

const originalGetJournalTrades = api.getJournalTrades.bind(api);

function performancePageIsActive(): boolean {
  const nav = document.getElementById("nav-performance-strategy");
  return Boolean(nav?.className.includes("bg-rose-500/10"));
}

api.getJournalTrades = async (token: string) => {
  const response = await originalGetJournalTrades(token);
  if (!performancePageIsActive()) return response;

  return {
    ...response,
    trades: response.trades.filter(
      (trade) => (trade as typeof trade & { performance_eligible?: boolean }).performance_eligible === true,
    ),
  };
};

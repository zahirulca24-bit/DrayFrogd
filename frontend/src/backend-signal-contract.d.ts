export {};

declare global {
  interface Object {
    trade_type?: "scalping" | "intraday" | null;
  }
}

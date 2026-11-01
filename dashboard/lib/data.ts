// Shapes of the JSON files the Python engine publishes. Kept loose where the dashboard only displays a field.

export type Status = "pass" | "wait" | "reject";
export type DecisionKind = "trade" | "wait" | "reject";

export interface FloorVerdict { floor: string; status: Status; summary: string }
export interface Decision {
  ts: string; coin: string; decision: DecisionKind; reason: string; floors: FloorVerdict[];
  price: number; entry: number; stop: number; target: number; units: number; notional: number; thesis: string;
}
export interface Opportunity {
  coin: string; price: number; ret_24h: number; ret_7d: number; volume_usd_24h: number; atr_pct: number;
  rsi: number; trend: "up" | "down" | "mixed"; volume_ratio: number; breakout: boolean; score: number; reasons: string[];
}
export interface Position {
  coin: string; units: number; entry_price: number; entry_ts: string; stop: number; initial_stop: number;
  target: number; mark: number; value: number; unrealized: number; unrealized_pct: number; r_now: number;
}
export interface Fill { ts: string; coin: string; side: "buy" | "sell"; price: number; units: number; fee: number; reason: string; pnl: number | null }
export interface Trade { coin: string; entry_ts: string; exit_ts: string; entry_price: number; exit_price: number; units: number; pnl: number; r_multiple: number; exit_reason: string }
export interface Alert { ts: string; level: "info" | "good" | "warn" | "bad"; coin: string; text: string }
export interface Message { ts: string; sender: string; receiver: string; kind: string; text: string }
export interface Check { name: string; passed: boolean; value: string; limit: string; severity: "wait" | "reject" }
export interface TestReport { coin: string; status: Status; trades: number; win_rate: number; expectancy_r: number; pooled_trades: number; pooled_expectancy_r: number; basis: string; reason: string; recent: number[] }
export interface Review { coin: string; verdict: string; confidence: number; thesis: string; risks: string[]; model: string }
export interface ResearchNote { coin: string; sentiment: number; headlines: { title: string; source: string; link?: string }[]; catalysts: string[]; red_flags: string[]; counterpoints: string[]; summary: string; blocking: boolean }
export interface Chart { coin: string; bars: [number, number, number, number, number, number][]; ema50: (number | null)[]; ema200: (number | null)[] }

export interface Metrics {
  total_return?: number; cagr?: number; sharpe?: number; sortino?: number; max_drawdown?: number; calmar?: number;
  trades: number; win_rate: number; avg_r: number; profit_factor: number | null;
}

export interface Snapshot {
  generated_at: string; as_of: string; next_decision: string; started_at: string; runs: number; mode: string;
  llm: { calls: number; cost_usd: number; name: string };
  config: { universe: string[]; starting_cash: number; risk: Record<string, number | boolean>; costs: Record<string, number> };
  scanner: Opportunity[];
  latest: { ts?: string; decisions?: Decision[]; research?: Record<string, ResearchNote>; reviews?: Record<string, Review>; tests?: Record<string, TestReport>; risk?: Record<string, { checks: Check[]; approved: boolean; reason: string }> };
  decisions: Decision[];
  messages: Message[];
  headlines: { title: string; source: string; link?: string }[];
  portfolio: {
    equity: number; cash: number; exposure: number; positions: Position[]; pending: unknown[]; metrics: Metrics;
    equity_hourly_30d: [string, number][]; equity_daily: [string, number][];
    trades: Trade[]; fills: Fill[]; alerts: Alert[];
  };
  charts: Record<string, Chart>;
}

export interface Variant {
  metrics: Metrics & { time_in_market?: number };
  decisions: Record<string, number>; stopped_at: Record<string, number>;
  equity: [string, number][]; yearly: Record<string, number>; trades: Trade[];
}
export interface Backtest {
  period: { start: string; end: string }; coins: string[];
  variants: Record<string, Variant>;
  benchmarks: Record<string, { metrics: Metrics; equity: [string, number][]; yearly: Record<string, number> }>;
  decision_log_sample?: Decision[];
}
export interface Ablation {
  period_start: string; setups_total: number; reviewed: number; valid_reviews: number; unavailable: number;
  all: { n: number; avg_r: number; win_rate: number }; approved: { n: number; avg_r: number; win_rate: number };
  vetoed: { n: number; avg_r: number; win_rate: number }; diff_avg_r_ci95: [number, number]; llm_cost_usd: number;
}

const REPO = "Tanzil-Ali-Rizvi/agent-trading-firm";
export const LIVE_URL = process.env.NEXT_PUBLIC_SNAPSHOT_URL ?? `https://raw.githubusercontent.com/${REPO}/data/snapshot.json`;
export const RESULTS_URL = process.env.NEXT_PUBLIC_RESULTS_URL ?? `https://raw.githubusercontent.com/${REPO}/main/results`;
export const REPO_URL = `https://github.com/${REPO}`;

export type Source = "live" | "sample";

async function getJson<T>(url: string): Promise<T | null> {
  try {
    const r = await fetch(url, { cache: "no-store" });
    return r.ok ? ((await r.json()) as T) : null;
  } catch {
    return null;
  }
}

export async function loadSnapshot(): Promise<{ data: Snapshot | null; source: Source }> {
  const live = await getJson<Snapshot>(`${LIVE_URL}?t=${Math.floor(Date.now() / 60000)}`);
  if (live) return { data: live, source: "live" };
  return { data: await getJson<Snapshot>("sample/snapshot.json"), source: "sample" };
}

export async function loadBacktest(): Promise<{ data: Backtest | null; ablation: Ablation | null; source: Source }> {
  const bt = await getJson<Backtest>(`${RESULTS_URL}/backtest.json`);
  if (bt) return { data: bt, ablation: await getJson<Ablation>(`${RESULTS_URL}/llm_ablation.json`), source: "live" };
  return { data: await getJson<Backtest>("sample/backtest.json"), ablation: null, source: "sample" };
}

// ---------------------------------------------------------------- formatting
export const usd = (x: number, dp = 2) =>
  `${x < 0 ? "-" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
export const pct = (x: number | undefined, dp = 1, sign = true) =>
  x === undefined || x === null || Number.isNaN(x) ? "–" : `${sign && x > 0 ? "+" : ""}${(x * 100).toFixed(dp)}%`;
export const price = (x: number) =>
  x >= 1000 ? x.toLocaleString("en-US", { maximumFractionDigits: 0 }) : x >= 1 ? x.toFixed(2) : x.toPrecision(4);
export const compact = (x: number) =>
  x >= 1e9 ? `$${(x / 1e9).toFixed(1)}B` : x >= 1e6 ? `$${(x / 1e6).toFixed(1)}M` : `$${(x / 1e3).toFixed(0)}K`;
export function ago(iso: string, now = Date.now()): string {
  const m = Math.round((now - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`;
}
export const hhmm = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";

export const FLOORS = [
  { key: "scanner", n: "01", name: "Scanner", job: "Finds a move worth investigating" },
  { key: "research", n: "02", name: "Research", job: "Checks the story: sources, catalysts, contrary evidence" },
  { key: "strategy", n: "03", name: "Strategy", job: "Turns the idea into entry, exit and invalidation" },
  { key: "testing", n: "04", name: "Testing", job: "Tests the rule on past data after fees and slippage" },
  { key: "risk", n: "05", name: "Risk", job: "Position size, exposure and loss limits" },
  { key: "control", n: "06", name: "Control", job: "Final call: trade, wait or reject" },
] as const;

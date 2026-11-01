"use client";

import { useMemo, useState } from "react";
import {
  Ablation, Backtest, Decision, FLOORS, Snapshot, compact, hhmm, pct, price, usd,
} from "@/lib/data";
import { CandleChart, LineCompare } from "./Charts";

// ---------------------------------------------------------------- idea journeys
export function Journeys({ decisions }: { decisions: Decision[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!decisions.length) return <p className="empty">No idea has reached the scanner's shortlist yet. The floors meet every four hours.</p>;
  return (
    <div className="journeys">
      {decisions.slice(0, 14).map((d) => {
        const id = `${d.ts}-${d.coin}`;
        const byFloor = Object.fromEntries(d.floors.map((f) => [f.floor, f]));
        const isOpen = open === id;
        return (
          <div className="journey" key={id}>
            <button onClick={() => setOpen(isOpen ? null : id)} aria-expanded={isOpen}>
              <span className="coin">{d.coin}</span>
              <span className="when">{hhmm(d.ts)}</span>
              <span className="mid">
                <span className="track" aria-label={`Floors passed: ${d.floors.filter((f) => f.status === "pass").length} of 6`}>
                  {FLOORS.map((f) => (
                    <span key={f.key} className={byFloor[f.key]?.status ?? ""} title={`${f.name}: ${byFloor[f.key]?.status ?? "not reached"}`} />
                  ))}
                </span>
                <span className="why">{d.decision === "trade" ? `Bought: ${d.thesis || "all floors passed"}` : d.reason.replace(/^(\w)/, (c) => c.toUpperCase())}</span>
              </span>
              <span className={`badge ${d.decision}`}>{d.decision}</span>
            </button>
            {isOpen ? (
              <div className="detail">
                {FLOORS.map((f) => {
                  const v = byFloor[f.key];
                  return (
                    <div className="step" key={f.key}>
                      <b>{f.n} {f.name}</b>
                      <span className={`st ${v?.status === "pass" ? "gain" : v?.status === "wait" ? "waitc" : v ? "loss" : "muted"}`}>{v?.status ?? "not reached"}</span>
                      <span className={v ? "" : "muted"}>{v?.summary ?? "The idea stopped before this floor."}</span>
                    </div>
                  );
                })}
                {d.thesis ? <div className="thesis">{d.thesis}</div> : null}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- market
export function Market({ snap }: { snap: Snapshot }) {
  const coins = Object.keys(snap.charts);
  const [coin, setCoin] = useState(coins[0]);
  const pos = snap.portfolio.positions.find((p) => p.coin === coin);
  return (
    <div className="grid-main">
      <div className="panel">
        <h3>
          {coin} <small>4-hour candles, EMA50 (amber) and EMA200 (violet)</small>
        </h3>
        <div className="coin-pick" role="group" aria-label="Choose a chart">
          {coins.map((c) => (
            <button key={c} aria-pressed={c === coin} onClick={() => setCoin(c)}>{c}</button>
          ))}
        </div>
        {snap.charts[coin] ? <CandleChart data={snap.charts[coin]} position={pos} /> : null}
      </div>
      <div className="panel">
        <h3>Scanner <small>ranked every 4 hours</small></h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Coin</th><th>Price</th><th>24h</th><th>7d</th><th>Vol 24h</th><th>Score</th></tr>
            </thead>
            <tbody>
              {snap.scanner.map((o) => (
                <tr key={o.coin} className={`clickable ${o.coin === coin ? "sel" : ""}`} onClick={() => snap.charts[o.coin] && setCoin(o.coin)}
                    title={o.reasons.join("; ") || undefined}>
                  <td className="coin"><span className={`trend ${o.trend}`} />{o.coin}{o.breakout ? " ↑" : ""}</td>
                  <td>{price(o.price)}</td>
                  <td className={o.ret_24h >= 0 ? "gain" : "loss"}>{pct(o.ret_24h)}</td>
                  <td className={o.ret_7d >= 0 ? "gain" : "loss"}>{pct(o.ret_7d)}</td>
                  <td>{compact(o.volume_usd_24h)}</td>
                  <td>{o.score.toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ fontSize: 12.5, marginBottom: 0 }}>Square: trend (green up, red down). ↑ marks a breakout above the 20-bar high.</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- the book
export function Book({ snap }: { snap: Snapshot }) {
  const p = snap.portfolio;
  const m = p.metrics;
  const ret = p.equity / snap.config.starting_cash - 1;
  return (
    <>
      <div className="kpis">
        <div className="kpi"><span>Equity (started at {usd(snap.config.starting_cash, 0)})</span><strong className={ret >= 0 ? "gain" : "loss"}>{usd(p.equity)}</strong></div>
        <div className="kpi"><span>Return since {new Date(snap.started_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</span><strong>{pct(ret, 2)}</strong></div>
        <div className="kpi"><span>Closed trades (win rate)</span><strong>{m.trades} <small style={{ fontSize: 15 }}>({m.trades ? pct(m.win_rate, 0, false) : "–"})</small></strong></div>
        <div className="kpi"><span>Max drawdown</span><strong>{pct(m.max_drawdown ?? 0, 1)}</strong></div>
      </div>
      <div className="grid-main">
        <div className="panel">
          <h3>Equity <small>marked to market every hour</small></h3>
          {p.equity_hourly_30d.length > 1 ? (
            <LineCompare small label="Paper account equity" sets={[{ name: "equity", color: "#8c87f5", points: p.equity_hourly_30d }]} />
          ) : <p className="empty">The curve starts after the first few hourly runs.</p>}
          <h3 style={{ marginTop: 18 }}>Open positions</h3>
          {p.positions.length ? (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Coin</th><th>Entry</th><th>Mark</th><th>Stop</th><th>Target</th><th>P&amp;L</th><th>R</th></tr></thead>
                <tbody>
                  {p.positions.map((x) => (
                    <tr key={x.coin}>
                      <td className="coin">{x.coin}</td><td>{price(x.entry_price)}</td><td>{price(x.mark)}</td>
                      <td>{price(x.stop)}</td><td>{price(x.target)}</td>
                      <td className={x.unrealized >= 0 ? "gain" : "loss"}>{usd(x.unrealized)}</td>
                      <td>{x.r_now.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="empty">Flat. No position is open, which is often the right answer.</p>}
        </div>
        <div className="panel">
          <h3>Fills and alerts</h3>
          <ul className="feed">
            {[...p.fills.map((f) => ({ ts: f.ts, cls: f.side === "buy" ? "" : (f.pnl ?? 0) >= 0 ? "lvl-good" : "lvl-bad",
              text: `${f.side === "buy" ? "Bought" : `Sold (${f.reason})`} ${f.units.toPrecision(4)} ${f.coin} at ${price(f.price)}${f.pnl != null ? `, ${usd(f.pnl)}` : ""}` })),
              ...p.alerts.filter((a) => !a.text.startsWith("Bought") && !a.text.startsWith("Closed")).map((a) => ({ ts: a.ts, cls: `lvl-${a.level}`, text: a.text }))]
              .sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, 40)
              .map((e, i) => (
                <li key={i}><time>{hhmm(e.ts).replace(" UTC", "")}</time><span className={e.cls}>{e.text}</span></li>
              ))}
            {!p.fills.length && !p.alerts.length ? <li><span className="muted">Nothing yet.</span></li> : null}
          </ul>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- testing the rules
const COLORS = ["#8c87f5", "#f2b35b", "#4cc38a", "#e5636b", "#5b8def", "#b9b6d6", "#ede6d6"];

export function TestingFloor({ bt, ablation, sample }: { bt: Backtest; ablation: Ablation | null; sample: boolean }) {
  const rows = useMemo(() => [
    ...Object.entries(bt.variants).map(([name, v]) => ({ name, m: v.metrics, kind: "firm" as const })),
    ...Object.entries(bt.benchmarks).map(([name, v]) => ({ name, m: v.metrics, kind: "bench" as const })),
  ], [bt]);
  const sets = useMemo(() => {
    const pick = ["full firm (rules, no LLM)", "without testing and risk"];
    return [
      ...pick.filter((k) => bt.variants[k]).map((k, i) => ({ name: k, color: COLORS[i], points: bt.variants[k].equity, width: (i === 0 ? 3 : 2) as 2 | 3 })),
      ...Object.entries(bt.benchmarks).map(([k, v], i) => ({ name: k, color: COLORS[4 + i], points: v.equity, width: 1 as const })),
    ];
  }, [bt]);
  const full = bt.variants["full firm (rules, no LLM)"];
  const stops = full ? Object.entries(full.stopped_at) : [];
  const maxStop = Math.max(1, ...stops.map(([, n]) => n));
  return (
    <>
      <div className="panel" style={{ marginBottom: 24 }}>
        <h3>Firm versus buy and hold <small>{bt.period.start.slice(0, 10)} to {bt.period.end.slice(0, 10)}, growth of 100</small></h3>
        <LineCompare normalise label="Backtest equity curves" sets={sets} />
        <div className="legend">
          {sets.map((s) => <span key={s.name}><i style={{ background: s.color }} />{s.name}</span>)}
        </div>
      </div>
      <div className="grid-main">
        <div className="panel">
          <h3>Results <small>fees and slippage included</small></h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th>System</th><th>Return</th><th>Sharpe</th><th>Max DD</th><th>Trades</th><th>Avg R</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.name} className={r.name.startsWith("full firm (rules") ? "highlight" : ""}>
                    <td>{r.name}</td>
                    <td className={(r.m.total_return ?? 0) >= 0 ? "gain" : "loss"}>{pct(r.m.total_return, 0)}</td>
                    <td>{(r.m.sharpe ?? 0).toFixed(2)}</td>
                    <td>{pct(r.m.max_drawdown, 0)}</td>
                    <td>{r.kind === "firm" ? r.m.trades : "–"}</td>
                    <td>{r.kind === "firm" && r.m.trades ? r.m.avg_r.toFixed(2) : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {sample ? <p className="note">These numbers come from synthetic data used to test the code. Real results appear when the backtest workflow has run on Coinbase data.</p> : null}
        </div>
        <div className="panel">
          <h3>Where ideas stopped <small>full firm</small></h3>
          <div className="bars">
            {stops.map(([k, n]) => {
              const [floor, outcome] = k.split(":");
              return (
                <div className="bar" key={k}>
                  <span>{floor} <span className="muted">{outcome}</span></span>
                  <div><i style={{ width: `${(n / maxStop) * 100}%`, background: outcome === "trade" ? "var(--gain)" : outcome === "wait" ? "var(--wait)" : "var(--loss)" }} /></div>
                  <span style={{ textAlign: "right" }}>{n.toLocaleString()}</span>
                </div>
              );
            })}
          </div>
          <h3 style={{ marginTop: 22 }}>Does the LLM review help?</h3>
          {ablation ? (
            <>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Setups</th><th>Count</th><th>Avg R</th><th>Win rate</th></tr></thead>
                  <tbody>
                    <tr><td>All reviewed</td><td>{ablation.all.n}</td><td>{ablation.all.avg_r.toFixed(2)}</td><td>{pct(ablation.all.win_rate, 0, false)}</td></tr>
                    <tr><td>LLM approved</td><td>{ablation.approved.n}</td><td>{ablation.approved.avg_r.toFixed(2)}</td><td>{pct(ablation.approved.win_rate, 0, false)}</td></tr>
                    <tr><td>LLM vetoed</td><td>{ablation.vetoed.n}</td><td>{ablation.vetoed.avg_r.toFixed(2)}</td><td>{pct(ablation.vetoed.win_rate, 0, false)}</td></tr>
                  </tbody>
                </table>
              </div>
              <p className="muted" style={{ fontSize: 13 }}>
                Approved minus vetoed, 95% interval: {ablation.diff_avg_r_ci95[0].toFixed(2)}R to {ablation.diff_avg_r_ci95[1].toFixed(2)}R.
                Setups were anonymised (no coin names or dates) so the model could not answer with hindsight.
              </p>
            </>
          ) : <p className="empty">The LLM ablation runs in the backtest workflow when a Groq key is configured.</p>}
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- floor log
export function Chatter({ snap }: { snap: Snapshot }) {
  const label = (s: string) => FLOORS.find((f) => f.key === s)?.name ?? (s === "executor" ? "Execution" : s === "portfolio" ? "Portfolio" : s);
  return (
    <div className="panel">
      <h3>Floor log <small>messages between floors, newest first</small></h3>
      <ul className="feed" style={{ maxHeight: 420 }}>
        {snap.messages.slice(0, 80).map((m, i) => (
          <li key={i}><time>{hhmm(m.ts).replace(" UTC", "")}</time><span><span className="who">{label(m.sender)}</span>{m.text}</span></li>
        ))}
        {!snap.messages.length ? <li><span className="muted">No messages yet.</span></li> : null}
      </ul>
    </div>
  );
}

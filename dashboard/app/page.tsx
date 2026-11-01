"use client";

import { useEffect, useState } from "react";
import Building from "@/components/Building";
import { Book, Chatter, Journeys, Market, TestingFloor } from "@/components/Sections";
import { Ablation, Backtest, REPO_URL, Snapshot, Source, ago, hhmm, loadBacktest, loadSnapshot, pct, usd } from "@/lib/data";

const SECTION_FOR: Record<string, string> = {
  scanner: "market", research: "ideas", strategy: "ideas", testing: "testing", risk: "book", control: "ideas",
};

function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true" shapeRendering="crispEdges">
      <rect x="3" y="2" width="14" height="22" fill="#2a2d5c" stroke="#8c87f5" strokeWidth="2" />
      {[5, 9, 13, 17].map((y) => <rect key={y} x="6" y={y} width="8" height="2" fill="#f2b35b" />)}
      <rect x="19" y="2" width="4" height="22" fill="#2a2d5c" stroke="#8c87f5" strokeWidth="2" />
      <rect x="20" y="9" width="2" height="4" fill="#8c87f5" />
    </svg>
  );
}

export default function Page() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [source, setSource] = useState<Source>("live");
  const [bt, setBt] = useState<{ data: Backtest | null; ablation: Ablation | null; source: Source } | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const s = await loadSnapshot();
      if (!alive) return;
      if (s.data) { setSnap(s.data); setSource(s.source); } else setError(true);
    };
    load();
    loadBacktest().then((b) => alive && setBt(b));
    const t = setInterval(load, 5 * 60 * 1000); // a new cycle is published every hour
    return () => { alive = false; clearInterval(t); };
  }, []);

  const jump = (key: string) => document.getElementById(SECTION_FOR[key])?.scrollIntoView({ behavior: "smooth", block: "start" });

  if (!snap) {
    return (
      <main className="wrap" style={{ padding: "80px 24px" }}>
        <p className="muted">{error ? "Could not load the firm's latest snapshot. Check your connection and reload the page." : "Opening the building…"}</p>
      </main>
    );
  }

  const full = bt?.data?.variants["full firm (rules, no LLM)"]?.metrics;
  const btc = bt?.data?.benchmarks["BTC buy & hold"]?.metrics;
  const ew = bt?.data?.benchmarks["equal-weight buy & hold (20 coins)"]?.metrics;
  const decisions = snap.decisions.length ? snap.decisions : snap.latest.decisions ?? [];

  return (
    <>
      <header className="topbar">
        <div className="wrap">
          <a className="wordmark" href="#top"><Logo />Agent Trading Firm</a>
          <div className="status" aria-live="polite">
            <span><i className={`dot ${source === "sample" ? "sample" : ""}`} />{source === "sample" ? "Sample data" : "Paper trading"}</span>
            {source === "live" ? (
              <>
                <span>Updated <b>{ago(snap.as_of)}</b></span>
                <span>Next decision <b>{hhmm(snap.next_decision)}</b></span>
              </>
            ) : <span>Synthetic prices</span>}
            <span>LLM <b>{snap.llm.name === "none" ? "off (rules only)" : "Groq via llm-gateway"}</b></span>
          </div>
          <div className="equity"><span>Paper equity</span><strong>{usd(snap.portfolio.equity, 0)}</strong></div>
        </div>
      </header>
      {source === "sample" ? (
        <div className="banner"><div className="wrap">Showing a sample run on synthetic prices. Live paper trading appears here after the first hourly cycle has run.</div></div>
      ) : null}

      <main className="wrap" id="top">
        <div className="hero">
          <div>
            <h1>Six floors.<span className="climb">Every trade has to climb all of them.</span></h1>
            <p className="lede">
              An AI trading firm where each floor has one job. The scanner finds a move, research checks the story,
              strategy writes the rules, testing proves them on past data, risk sets the limits, and control makes the
              call. Most ideas stop on the way up, and waiting counts as a decision.
            </p>
            {full && btc ? (
              <div className="proof">
                <div className="row"><span>Backtest return, firm (rules only)</span><strong>{pct(full.total_return, 0)}</strong><span className="muted">max drawdown {pct(full.max_drawdown, 0)}</span></div>
                <div className="row"><span>Bitcoin, bought and held</span><strong>{pct(btc.total_return, 0)}</strong><span className="muted">max drawdown {pct(btc.max_drawdown, 0)}</span></div>
                {ew ? <div className="row"><span>All 20 coins, bought and held</span><strong>{pct(ew.total_return, 0)}</strong><span className="muted">max drawdown {pct(ew.max_drawdown, 0)}</span></div> : null}
                <span className="caption">
                  {bt?.source === "sample" ? "Synthetic test data. " : ""}{bt?.data?.period.start.slice(0, 10)} to {bt?.data?.period.end.slice(0, 10)}, hourly bars, fees and slippage included. Paper trading only, not investment advice.
                </span>
              </div>
            ) : null}
            <div className="actions">
              <a className="btn primary" href="#ideas">Follow the latest ideas</a>
              <a className="btn" href={REPO_URL}>Read the code</a>
            </div>
          </div>
          <Building snap={snap} onSelect={jump} />
        </div>

        <section className="block" id="ideas">
          <h2>The elevator log</h2>
          <p className="intro">Every idea the scanner sends up, floor by floor. Open one to see why each floor passed it, held it or turned it away.</p>
          <Journeys decisions={decisions} />
        </section>

        <section className="block" id="market">
          <h2>The market, as the scanner sees it</h2>
          <p className="intro">20 liquid coins from Coinbase, hourly candles combined into 4-hour bars. Click a row to chart it.</p>
          <Market snap={snap} />
        </section>

        <section className="block" id="book">
          <h2>The book</h2>
          <p className="intro">
            A {usd(snap.config.starting_cash, 0)} paper account. Each trade risks {pct(Number(snap.config.risk.risk_per_trade), 0, false)} of equity at most, entries fill at the next
            hour's open with {pct(snap.config.costs.fee_rate, 2, false)} fees and {pct(snap.config.costs.slippage_rate, 2, false)} slippage per side.
          </p>
          <Book snap={snap} />
        </section>

        <section className="block" id="testing">
          <h2>Testing the rules before trusting them</h2>
          <p className="intro">
            The same code that trades live was replayed over two years of hourly data. Then floors were switched off one at a time, and fees raised to retail
            levels, to see what each part is worth.
          </p>
          {bt?.data ? <TestingFloor bt={bt.data} ablation={bt.ablation} sample={bt.source === "sample"} /> : <p className="empty">Loading backtest results…</p>}
          {bt?.source === "live" ? (
            <div className="note" style={{ maxWidth: "52em", marginTop: 24 }}>
              <p style={{ margin: "0 0 8px" }}>
                <b>What this says.</b> The entry rule has no reliable edge after costs: the average trade is close to 0R in every variant. The risk floor does
                its job, roughly halving the worst drawdown compared with the same rule without limits. The testing floor did not add value in this period.
                At retail exchange fees the same firm loses money clearly. In an anonymised test, the setups the LLM vetoed did better than the ones it
                approved, so its opinion is now advisory only.
              </p>
              <p style={{ margin: 0 }}>
                Parameters were fixed before the run and not tuned afterwards. The system works; this strategy inside it doesn't, and the firm is built to show
                exactly that.
              </p>
            </div>
          ) : null}
        </section>

        <section className="block" id="log">
          <h2>On the floors right now</h2>
          <p className="intro">What the floors told each other in recent cycles.</p>
          <Chatter snap={snap} />
        </section>
      </main>

      <footer>
        <div className="wrap">
          <span>Paper trading with simulated money. Nothing here is investment advice.</span>
          <span>
            Built by Tanzil Ali Rizvi. <a href={REPO_URL}>Source on GitHub</a>. LLM calls run through <a href="https://github.com/Tanzil-Ali-Rizvi/llm-gateway">llm-gateway</a>.
          </span>
        </div>
      </footer>
    </>
  );
}

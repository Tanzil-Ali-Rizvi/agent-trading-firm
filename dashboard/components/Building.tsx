"use client";

import { useEffect, useState } from "react";
import { FLOORS, Snapshot, Decision, pct, ago } from "@/lib/data";

// One colour per crew so a floor is recognisable at a glance. Blocky "voxel" workers echo the firm-building idea.
const CREW: Record<string, string[]> = {
  scanner: ["#4cc38a", "#5b8def"],
  research: ["#8c6cf0", "#e9c46a", "#5b8def"],
  strategy: ["#e5636b", "#5b8def", "#4cc38a"],
  testing: ["#8c6cf0", "#5b8def", "#e5636b"],
  risk: ["#4cc38a", "#e9c46a", "#8c6cf0"],
  control: ["#4cc38a", "#8c6cf0", "#f08a4b"],
};

function Worker({ color, seated = true }: { color: string; seated?: boolean }) {
  return (
    <svg width="26" height="56" viewBox="0 0 26 56" aria-hidden="true" shapeRendering="crispEdges">
      <rect x="5" y="2" width="16" height="15" fill={color} />
      <rect x="5" y="2" width="16" height="4" fill="rgba(255,255,255,.18)" />
      <rect x="9" y="8" width="2" height="3" fill="#16163a" />
      <rect x="15" y="8" width="2" height="3" fill="#16163a" />
      <rect x="3" y="18" width="20" height="18" fill={color} />
      <rect x="3" y="18" width="20" height="18" fill="rgba(0,0,0,.18)" />
      <rect x="0" y="20" width="4" height="12" fill={color} />
      <rect x="22" y="20" width="4" height="12" fill={color} />
      {seated ? <rect x="1" y="36" width="24" height="8" fill="#191a3a" /> : null}
      <rect x="6" y={seated ? 44 : 36} width="5" height={seated ? 12 : 20} fill="#191a3a" />
      <rect x="15" y={seated ? 44 : 36} width="5" height={seated ? 12 : 20} fill="#191a3a" />
    </svg>
  );
}

function floorScreen(key: string, s: Snapshot): { head: string; when?: string; body: string } {
  const latest = s.latest ?? {};
  const decisions = latest.decisions ?? [];
  const reached = (k: string) => decisions.filter((d) => d.floors.some((f) => f.floor === k));
  switch (key) {
    case "scanner": {
      const top = s.scanner.slice(0, 3);
      const ideas = s.scanner.filter((o) => o.trend === "up" && o.breakout).length;
      return {
        head: `${s.scanner.length} coins ranked, ${ideas} breaking out`,
        when: ago(s.as_of),
        body: top.map((o) => `${o.coin} ${pct(o.ret_24h)} 24h`).join("   ") || "Waiting for data",
      };
    }
    case "research": {
      const notes = Object.values(latest.research ?? {});
      const n = notes[0];
      return n
        ? { head: `${notes.length} coin${notes.length > 1 ? "s" : ""} researched`, body: `${n.coin}: ${n.summary}` }
        : { head: `${s.headlines.length} headlines read`, body: s.headlines[0]?.title ?? "No ideas to research this cycle" };
    }
    case "strategy": {
      const r = Object.values(latest.reviews ?? {})[0];
      const n = reached("strategy").length;
      return r
        ? { head: `${n} idea${n === 1 ? "" : "s"} turned into rules`, body: `${r.coin}: ${r.thesis || r.verdict}` }
        : { head: `${n} idea${n === 1 ? "" : "s"} checked against the entry rules`, body: reached("strategy")[0]?.floors.find((f) => f.floor === "strategy")?.summary ?? "Nothing reached this floor yet" };
    }
    case "testing": {
      const t = Object.values(latest.tests ?? {})[0];
      return t
        ? { head: `${t.coin}: ${t.status}`, body: t.reason }
        : { head: "Replays each rule on past data", body: "Only trades that had finished before the decision count" };
    }
    case "risk": {
      const p = s.portfolio;
      const openRisk = p.positions.reduce((a, x) => a + x.units * Math.max(0, x.entry_price - x.stop), 0);
      return {
        head: `${p.positions.length} of ${s.config.risk.max_open_positions} positions open`,
        body: `Exposure ${pct(p.exposure / p.equity, 0, false)} of equity, open risk ${pct(openRisk / p.equity, 1, false)} (limit ${pct(Number(s.config.risk.max_total_open_risk), 0, false)})`,
      };
    }
    default: {
      const c = { trade: 0, wait: 0, reject: 0 };
      decisions.forEach((d) => (c[d.decision] += 1));
      return {
        head: decisions.length ? `Last cycle: ${c.trade} trade, ${c.wait} wait, ${c.reject} reject` : "No ideas in the last cycle",
        when: latest.ts ? ago(latest.ts) : undefined,
        body: decisions[0] ? `${decisions[0].coin}: ${decisions[0].reason}` : "Waiting is a valid decision",
      };
    }
  }
}

function stopFloor(d: Decision | undefined): number {
  if (!d) return 0;
  if (d.decision === "trade") return 5;
  const i = FLOORS.findIndex((f) => f.key === d.floors.find((x) => x.status !== "pass")?.floor);
  return i < 0 ? 5 : i;
}

export default function Building({ snap, onSelect }: { snap: Snapshot; onSelect: (key: string) => void }) {
  const idea = snap.latest?.decisions?.[0] ?? snap.decisions[0];
  const target = stopFloor(idea);
  const [level, setLevel] = useState(0);
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => {
    const t = setTimeout(() => setLevel(target), 300); // the one orchestrated motion: the idea rides up
    return () => clearTimeout(t);
  }, [target]);
  const verdictColor = idea?.decision === "trade" ? "var(--gain)" : idea?.decision === "wait" ? "var(--wait)" : "var(--loss)";

  return (
    <div>
      <div className="building" role="group" aria-label="The firm: six floors">
        <div className="floors">
          {FLOORS.map((f) => {
            const sc = floorScreen(f.key, snap);
            return (
              <button
                key={f.key}
                className="floor"
                aria-pressed={active === f.key}
                onClick={() => {
                  setActive(f.key);
                  onSelect(f.key);
                }}
                title={f.job}
              >
                <div className="plaque">
                  <span className="n">{f.n}</span>
                  <span className="name">{f.name}</span>
                </div>
                <div className="room">
                  <div className="crew">
                    {CREW[f.key].map((c, i) => (
                      <Worker key={i} color={c} seated={!(f.key === "strategy" && i === 1)} />
                    ))}
                  </div>
                  <div className="screen">
                    <div className="head">
                      <span>{sc.head}</span>
                      {sc.when ? <em>{sc.when}</em> : null}
                    </div>
                    <div className="body">{sc.body}</div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
        <div className="shaft" aria-hidden={!idea}>
          {idea ? (
            <div className="car" style={{ bottom: `calc(${(level / 6) * 100}% + ${level === 0 ? 14 : 14}px)` }} aria-label={`Latest idea ${idea.coin}: ${idea.decision} at ${FLOORS[target].name}`}>
              <span className="ticket">{idea.coin}</span>
              <span className="verdict" style={{ color: verdictColor }}>{idea.decision}</span>
            </div>
          ) : null}
        </div>
      </div>
      <div className="ground">
        <span>Click a floor to jump to its work</span>
        <span>{idea ? `Latest idea: ${idea.coin}, stopped at ${FLOORS[target].name}` : "No ideas yet"}</span>
      </div>
    </div>
  );
}

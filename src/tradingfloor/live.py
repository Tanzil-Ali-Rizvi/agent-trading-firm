"""Live paper trading: one run per hour (GitHub Actions cron), state carried between runs in JSON files.

Each run: update the hourly candle cache from Coinbase, load the firm's state, process every hour that closed since
the last run (exits are always processed; only the newest 4-hour boundary may open new trades, so a delayed run
never trades on stale news), then write `state.json` (to resume) and `snapshot.json` (what the dashboard reads).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .agents.executor import PaperBroker
from .agents.portfolio import PortfolioDesk
from .agents.research import fetch_headlines
from .config import FloorConfig
from .firm import CycleReport, Switches, TradingFirm
from .llm import LLM, from_env
from .market import H1, H4, MarketData, download, floor_hour, load, save
from .metrics import equity_metrics, trade_metrics
from .models import to_dict

HISTORY_DAYS = 420  # the testing floor needs a year of finished trades plus indicator warm-up
MAX_CATCH_UP_HOURS = 24 * 7


async def update_market(cache: Path, coins: list[str], now: pd.Timestamp) -> dict[str, pd.DataFrame]:
    h1 = load(cache) if cache.exists() else {}
    earliest = now - pd.Timedelta(days=HISTORY_DAYS)
    starts = {c: (h1[c].index[-1] + H1 if c in h1 and len(h1[c]) else earliest) for c in coins}
    fresh = {}
    for c in coins:
        if starts[c] < now:
            got = await download([c], starts[c].to_pydatetime(), now.to_pydatetime())
            fresh[c] = got[c]
    for c in coins:
        parts = [df for df in (h1.get(c), fresh.get(c)) if df is not None and len(df)]
        if parts:
            df = pd.concat(parts)
            df = df[~df.index.duplicated(keep="last")].sort_index()
            h1[c] = df[df.index >= earliest]
    save(h1, cache)
    return h1


def load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return {}


async def run_live(state_dir: Path, cache: Path, llm: LLM | None = None, now: pd.Timestamp | None = None,
                   h1: dict[str, pd.DataFrame] | None = None, headlines: list[dict[str, str]] | None = None) -> dict[str, Any]:  # fmt: skip
    cfg = FloorConfig()
    now = now or floor_hour(datetime.now(UTC))
    state_dir.mkdir(parents=True, exist_ok=True)
    st = load_state(state_dir / "state.json")
    if h1 is None:
        h1 = await update_market(cache, cfg.universe, now)
    data = MarketData(h1, cfg.strategy)
    if headlines is None:
        headlines = await fetch_headlines()
    llm = llm if llm is not None else from_env(cfg.llm.route)

    broker = PaperBroker.from_dict(cfg, st["broker"]) if "broker" in st else PaperBroker(cfg)
    portfolio = PortfolioDesk.from_dict(st["portfolio"]) if "portfolio" in st else PortfolioDesk()
    firm = TradingFirm(cfg, data, broker, portfolio, llm, Switches(), headlines, record_messages=True)
    firm.llm_calls = st.get("llm", {}).get("calls", 0)
    firm.llm_cost = st.get("llm", {}).get("cost_usd", 0.0)

    last = pd.Timestamp(st["last_processed"]) if "last_processed" in st else now - H1
    last = max(last, now - pd.Timedelta(hours=MAX_CATCH_UP_HOURS))
    hours = list(pd.date_range(last + H1, now, freq="1h"))
    latest_boundary = max((h for h in hours if h.hour % cfg.decision_hours == 0), default=None)
    report: CycleReport | None = None
    for h in hours:
        r = await firm.step(h, allow_decide=(h == latest_boundary))
        report = r or report

    view = data.view(now)
    opps = firm.scanner.scan(view)  # refresh the scanner table every run, even between decision cycles
    latest = st.get("latest", {})
    if report is not None:
        latest = {
            "ts": report.ts,
            "research": {k: to_dict(v) for k, v in report.research.items()},
            "reviews": {k: to_dict(v) for k, v in report.reviews.items()},
            "tests": {k: to_dict(v) for k, v in report.tests.items()},
            "risk": report.risk,
            "decisions": [to_dict(d) for d in report.decisions],
        }
    decisions = (st.get("decisions", []) + [to_dict(d) for d in firm.decisions])[-300:]
    messages = (st.get("messages", []) + [to_dict(m) for m in firm.messages])[-300:]
    state = {
        "started_at": st.get("started_at", now.isoformat()),
        "last_processed": now.isoformat(),
        "runs": st.get("runs", 0) + 1,
        "broker": broker.to_dict(),
        "portfolio": portfolio.to_dict(),
        "decisions": decisions,
        "messages": messages,
        "latest": latest,
        "llm": {"calls": firm.llm_calls, "cost_usd": round(firm.llm_cost, 6), "name": getattr(llm, "name", "none")},
    }
    (state_dir / "state.json").write_text(json.dumps(state, default=str))
    snap = snapshot(cfg, data, view, firm, opps, state, headlines)
    (state_dir / "snapshot.json").write_text(json.dumps(snap, default=_json_default))
    return snap


def _json_default(o: Any) -> Any:
    if hasattr(o, "item"):
        return o.item()
    return str(o)


def candles(data: MarketData, view, coin: str, n: int = 120) -> dict[str, Any]:
    f = view.last_4h(coin, n)
    return {
        "coin": coin,
        "bars": [
            [int(t.timestamp()), *(round(float(r[k]), 10) for k in ("open", "high", "low", "close", "volume"))]
            for t, r in f.iterrows()
        ],  # fmt: skip
        "ema50": [None if pd.isna(x) else round(float(x), 10) for x in f["ema_fast"]],
        "ema200": [None if pd.isna(x) else round(float(x), 10) for x in f["ema_slow"]],
    }


def snapshot(cfg, data, view, firm: TradingFirm, opps, state, headlines) -> dict[str, Any]:
    b = firm.broker
    marks = b.marks(view)
    eq = firm.portfolio.series()
    positions = []
    for c, p in b.positions.items():
        m = marks.get(c, p.entry_price)
        positions.append({**to_dict(p), "mark": m, "value": p.units * m, "unrealized": p.units * (m - p.entry_price),
                          "unrealized_pct": m / p.entry_price - 1, "r_now": (m - p.entry_price) / p.risk_per_unit})  # fmt: skip
    chart_coins = list(dict.fromkeys([*b.positions, *[o.coin for o in opps[:6]], "BTC"]))[:8]
    last_hour = eq[eq.index >= eq.index[-1] - pd.Timedelta(days=30)] if len(eq) else eq
    nxt = (view.now.floor("4h") + H4).isoformat()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": view.now.isoformat(),
        "next_decision": nxt,
        "started_at": state["started_at"],
        "runs": state["runs"],
        "mode": "paper trading",
        "llm": state["llm"],
        "config": {
            "universe": cfg.universe,
            "starting_cash": cfg.starting_cash,
            "risk": cfg.risk.model_dump(),
            "strategy": cfg.strategy.model_dump(),
            "testing": cfg.testing.model_dump(),
            "costs": cfg.costs.model_dump(),
        },  # fmt: skip
        "scanner": [to_dict(o) for o in opps],
        "latest": state["latest"],
        "decisions": state["decisions"][-120:][::-1],
        "messages": state["messages"][-120:][::-1],
        "headlines": headlines[:30],
        "portfolio": {
            "equity": b.equity(marks),
            "cash": b.cash,
            "exposure": b.exposure(marks),
            "positions": positions,
            "pending": [to_dict(o) for o in b.pending.values()],
            "metrics": {**equity_metrics(eq), **trade_metrics(b.trades)} if len(eq) > 1 else trade_metrics(b.trades),
            "equity_hourly_30d": [[t.isoformat(), round(float(v), 2)] for t, v in last_hour.items()],
            "equity_daily": [
                [t.strftime("%Y-%m-%d"), round(float(v), 2)] for t, v in eq.resample("1D").last().dropna().items()
            ]
            if len(eq)
            else [],
            "trades": [to_dict(t) for t in b.trades][::-1][:100],
            "fills": [to_dict(f) for f in b.fills][::-1][:60],
            "alerts": [to_dict(a) for a in firm.portfolio.alerts][::-1][:40],
        },
        "charts": {c: candles(data, view, c) for c in chart_coins},
    }


def main_env() -> tuple[Path, Path]:
    return Path(os.getenv("STATE_DIR", "state")), Path(os.getenv("MARKET_CACHE", ".cache/market.json.gz"))

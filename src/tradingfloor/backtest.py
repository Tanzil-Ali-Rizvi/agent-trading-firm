"""Backtest: replay history hour by hour through the same `TradingFirm.step()` that runs live.

Reports the full firm against buy-and-hold benchmarks, then removes one floor at a time (ablations) and re-runs
with retail exchange fees, so the README can say what each part is worth rather than only how the best run did.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import FloorConfig
from .firm import Switches, TradingFirm
from .market import H1, MarketData, load, synthetic
from .metrics import equity_metrics, trade_metrics
from .models import to_dict


async def run(
    cfg: FloorConfig, data: MarketData, start: pd.Timestamp, end: pd.Timestamp, switches: Switches, llm=None
) -> dict[str, Any]:
    firm = TradingFirm(cfg, data, llm=llm, switches=switches)
    hours = [h + H1 for h in data.hours() if start <= h + H1 <= end]
    for now in hours:
        await firm.step(now)
    firm.broker.close_all(data.view(hours[-1]), "end of test")
    firm.portfolio.record(hours[-1], firm.broker)
    eq = firm.portfolio.series()
    outcomes: dict[str, int] = {}
    stops: dict[str, int] = {}
    for d in firm.decisions:
        outcomes[d.decision] = outcomes.get(d.decision, 0) + 1
        stop_floor = next((f.floor for f in d.floors if f.status != "pass"), "control")
        key = f"{stop_floor}:{d.decision}"
        stops[key] = stops.get(key, 0) + 1
    exposure = pd.Series([e[3] / e[1] if e[1] else 0 for e in firm.portfolio.equity])
    return {
        "metrics": {
            **equity_metrics(eq),
            **trade_metrics(firm.broker.trades),
            "time_in_market": float((exposure > 0.01).mean()),
            "avg_exposure": float(exposure.mean()),
        },  # fmt: skip
        "decisions": outcomes,
        "stopped_at": dict(sorted(stops.items(), key=lambda kv: -kv[1])),
        "equity": downsample(eq),
        "trades": [to_dict(t) for t in firm.broker.trades],
        "llm_calls": firm.llm_calls,
        "llm_cost_usd": round(firm.llm_cost, 4),
        "_firm": firm,
    }


def buy_and_hold(
    data: MarketData, coins: list[str], start: pd.Timestamp, end: pd.Timestamp, cfg: FloorConfig
) -> pd.Series:
    """Equal weight at `start`, never rebalanced, one round-trip of fees and slippage."""
    cost = cfg.costs.fee_rate + cfg.costs.slippage_rate
    parts = []
    for c in coins:
        s = data.h1[c]["close"]
        s = s[(s.index >= start - H1) & (s.index <= end - H1)]
        if len(s) < 2:
            continue
        parts.append(s / s.iloc[0])
    if not parts:
        return pd.Series(dtype=float)
    curve = pd.concat(parts, axis=1).ffill().mean(axis=1) * cfg.starting_cash * (1 - cost)
    curve.iloc[-1] *= 1 - cost
    curve.index = curve.index + H1
    return curve


def downsample(eq: pd.Series, rule: str = "1D") -> list[list[Any]]:
    if eq.empty:
        return []
    d = eq.resample(rule).last().dropna()
    return [[t.strftime("%Y-%m-%d"), round(float(v), 2)] for t, v in d.items()]


def yearly(eq: pd.Series) -> dict[str, float]:
    out = {}
    for y, s in eq.groupby(eq.index.year):
        if len(s) > 24 * 30:
            out[str(y)] = float(s.iloc[-1] / s.iloc[0] - 1)
    return out


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    cfg = FloorConfig()
    h1 = load(Path(args.data)) if args.data else synthetic(cfg.universe, hours=24 * 900, seed=args.seed)
    data = MarketData(h1, cfg.strategy)
    first = min(df.index[0] for df in data.h1.values())
    last = max(df.index[-1] for df in data.h1.values()) + H1
    start = pd.Timestamp(args.start, tz="UTC") if args.start else first + pd.Timedelta(days=args.warmup_days)
    end = pd.Timestamp(args.end, tz="UTC") if args.end else last
    print(f"backtest {start} -> {end} on {len(data.coins)} coins")

    variants = {
        "full firm (rules, no LLM)": (cfg, Switches(research=False, llm_review=False)),
        "without testing floor": (cfg, Switches(research=False, llm_review=False, testing=False)),
        "without risk floor": (cfg, Switches(research=False, llm_review=False, risk=False)),
        "without testing and risk": (cfg, Switches(research=False, llm_review=False, testing=False, risk=False)),
    }
    retail = cfg.model_copy(deep=True)
    retail.costs.fee_rate = 0.006  # Coinbase Advanced retail taker fee
    variants["full firm, retail fees (0.6%)"] = (retail, Switches(research=False, llm_review=False))

    results: dict[str, Any] = {"period": {"start": str(start), "end": str(end)}, "coins": data.coins,
                               "config": cfg.model_dump(), "variants": {}, "benchmarks": {}}  # fmt: skip
    for name, (c, sw) in variants.items():
        t0 = time.perf_counter()
        r = await run(c, data, start, end, sw)
        firm = r.pop("_firm")
        r["yearly"] = yearly(firm.portfolio.series())
        results["variants"][name] = r
        m = r["metrics"]
        print(f"{name:34s} return {m['total_return']:+.1%}  sharpe {m['sharpe']:.2f}  maxDD {m['max_drawdown']:.1%}  "
              f"trades {m['trades']}  ({time.perf_counter() - t0:.0f}s)")  # fmt: skip
        if name.startswith("full firm (rules"):
            results["decision_log_sample"] = [to_dict(d) for d in firm.decisions[-40:]]

    for name, coins in (("BTC buy & hold", ["BTC"]), ("equal-weight buy & hold (20 coins)", data.coins)):
        eq = buy_and_hold(data, coins, start, end, cfg)
        results["benchmarks"][name] = {"metrics": equity_metrics(eq), "equity": downsample(eq), "yearly": yearly(eq)}
        m = results["benchmarks"][name]["metrics"]
        print(f"{name:34s} return {m['total_return']:+.1%}  sharpe {m['sharpe']:.2f}  maxDD {m['max_drawdown']:.1%}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "backtest.json").write_text(json.dumps(results, default=_json) + "\n")
    (out / "backtest.md").write_text(to_md(results))
    return results


def _json(o: Any) -> Any:
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, float) and (np.isinf(o) or np.isnan(o)):
        return None
    return str(o)


def to_md(r: dict[str, Any]) -> str:
    def row(name: str, m: dict[str, float], trades: str = "") -> str:
        return (f"| {name} | {m['total_return']:+.1%} | {m['cagr']:+.1%} | {m['sharpe']:.2f} | {m['max_drawdown']:.1%} "
                f"| {trades} |")  # fmt: skip

    lines = [
        "# Backtest",
        "",
        f"{r['period']['start'][:10]} to {r['period']['end'][:10]}, {len(r['coins'])} coins, hourly bars, "
        "fills at the next bar's open with fees and slippage. Parameters were fixed before this run.",
        "",
        "| System | Return | CAGR | Sharpe | Max drawdown | Trades (win rate, avg R) |",
        "|---|---|---|---|---|---|",
    ]
    for name, v in r["variants"].items():
        m = v["metrics"]
        lines.append(row(name, m, f"{m['trades']} ({m['win_rate']:.0%}, {m['avg_r']:+.2f}R)"))
    for name, v in r["benchmarks"].items():
        lines.append(row(name, v["metrics"]))
    full = r["variants"].get("full firm (rules, no LLM)")
    if full:
        lines += ["", "Where ideas stopped (full firm):", "", "| Floor : outcome | Ideas |", "|---|---|"]
        lines += [f"| {k} | {n} |" for k, n in full["stopped_at"].items()]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="gzipped JSON of hourly candles (see `tradingfloor download`)")
    ap.add_argument("--out", default="results")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--warmup-days", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0)
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()

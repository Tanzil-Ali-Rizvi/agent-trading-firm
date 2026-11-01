"""LLM ablation: does the strategy floor's LLM review pick better trades than the rules alone?

Every setup that met the entry rules during the test period is replayed to its exit (same stop, breakeven,
trailing stop, target, fees and slippage as the executor), giving its result in R. A sample of those setups is then
shown to the LLM reviewer exactly as the live system shows them, but anonymised: no coin name and no dates, prices
indexed to 100. Otherwise the model could recognise "SOL in October 2025" and answer with hindsight.

If the reviewer helps, setups it approves should do better than the ones it rejects.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .agents.scanner import Scanner
from .agents.strategy import Strategy, signal_mask
from .agents.testing import arrays, replay_trade
from .config import FloorConfig
from .llm import from_env
from .market import H4, MarketData, load


def bootstrap_diff(a: np.ndarray, b: np.ndarray, n: int = 5000, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    d = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(n)]
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    cfg = FloorConfig()
    data = MarketData(load(Path(args.data)), cfg.strategy)
    start = pd.Timestamp(args.start, tz="UTC")
    llm = from_env("smart")
    if llm is None:
        raise SystemExit("set GROQ_API_KEY (or LLM_BASE_URL) to run the LLM ablation")
    strategy = Strategy(cfg, llm)
    scanner = Scanner(cfg)

    setups = []
    for coin, f in data.h4.items():
        mask = signal_mask(f, cfg.strategy).to_numpy()
        arr = arrays(f)
        for i in np.flatnonzero(mask):
            ts = f.index[i]
            if ts < start:
                continue
            out = replay_trade(arr, int(i), cfg)
            if out is not None:
                setups.append((coin, ts, out[0]))
    random.Random(7).shuffle(setups)
    sample = sorted(setups[: args.max_setups], key=lambda x: x[1])
    print(f"{len(setups)} setups met the rules after {start.date()}; reviewing {len(sample)}")

    rows = []
    for k, (coin, ts, r) in enumerate(sample):
        view = data.view(ts + H4)  # the decision is made when the signal bar closes
        opp = next(o for o in scanner.scan(view) if o.coin == coin)
        setup, _ = strategy.setup_for(opp, view)
        if setup is None:
            continue
        rev = await strategy.review(setup, view, anonymize=True)
        rows.append({"coin": coin, "ts": ts.isoformat(), "r": round(r, 3), "verdict": rev.verdict,
                     "confidence": rev.confidence, "vetoed": strategy.would_veto(rev), "model": rev.model,
                     "thesis": rev.thesis, "cost_usd": rev.cost_usd})  # fmt: skip
        if (k + 1) % 10 == 0:
            print(f"  {k + 1}/{len(sample)} reviewed")
        await asyncio.sleep(2.0)  # stay inside the free-tier rate limit

    df = pd.DataFrame(rows)
    ok = df[df.verdict.isin(["approve", "reject"])]
    kept, vetoed = ok[~ok.vetoed].r.to_numpy(), ok[ok.vetoed].r.to_numpy()
    lo, hi = bootstrap_diff(kept, vetoed)
    res = {
        "period_start": str(start.date()),
        "setups_total": len(setups),
        "reviewed": len(df),
        "valid_reviews": len(ok),
        "unavailable": int((df.verdict == "unavailable").sum()) if len(df) else 0,
        "all": {
            "n": len(ok),
            "avg_r": float(ok.r.mean()) if len(ok) else 0.0,
            "win_rate": float((ok.r > 0).mean()) if len(ok) else 0.0,
        },
        "approved": {
            "n": len(kept),
            "avg_r": float(kept.mean()) if len(kept) else 0.0,
            "win_rate": float((kept > 0).mean()) if len(kept) else 0.0,
        },
        "vetoed": {
            "n": len(vetoed),
            "avg_r": float(vetoed.mean()) if len(vetoed) else 0.0,
            "win_rate": float((vetoed > 0).mean()) if len(vetoed) else 0.0,
        },
        "diff_avg_r_ci95": [lo, hi],
        "llm_cost_usd": float(df.cost_usd.sum()) if len(df) else 0.0,
        "models": df.model.value_counts().to_dict() if len(df) else {},
        "rows": rows,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "llm_ablation.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    (out / "llm_ablation.md").write_text(to_md(res))
    print(to_md(res))
    return res


def to_md(r: dict[str, Any]) -> str:
    lo, hi = r["diff_avg_r_ci95"]
    return "\n".join([
        "# Does the LLM review help?",
        "",
        f"{r['setups_total']} setups met the entry rules after {r['period_start']}; a random {r['reviewed']} were "
        f"reviewed by the LLM (anonymised, no dates). {r['unavailable']} reviews failed.",
        "",
        "| Group | Setups | Avg result (R, after costs) | Win rate |",
        "|---|---|---|---|",
        f"| All reviewed | {r['all']['n']} | {r['all']['avg_r']:+.2f} | {r['all']['win_rate']:.0%} |",
        f"| LLM approved | {r['approved']['n']} | {r['approved']['avg_r']:+.2f} | {r['approved']['win_rate']:.0%} |",
        f"| LLM vetoed | {r['vetoed']['n']} | {r['vetoed']['avg_r']:+.2f} | {r['vetoed']['win_rate']:.0%} |",
        "",
        f"Approved minus vetoed, 95% bootstrap interval: {lo:+.2f}R to {hi:+.2f}R. "
        "If the interval includes zero, the review has no demonstrated edge on this sample.",
        "",
    ]) + "\n"  # fmt: skip

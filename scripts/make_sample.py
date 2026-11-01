"""Build dashboard/public/sample/*.json from synthetic prices, so the dashboard renders before any live run.

The dashboard labels this data as a synthetic sample wherever it is shown.
"""

import asyncio
import json
import shutil
from pathlib import Path

import pandas as pd

from tradingfloor.backtest import main_async
from tradingfloor.config import FloorConfig
from tradingfloor.firm import Switches, TradingFirm
from tradingfloor.live import _json_default, snapshot
from tradingfloor.market import H1, MarketData, synthetic
from tradingfloor.models import to_dict

OUT = Path("dashboard/public/sample")


async def live_sample() -> None:
    cfg = FloorConfig()
    data = MarketData(synthetic(cfg.universe, hours=24 * 520, seed=11), cfg.strategy)
    firm = TradingFirm(cfg, data, switches=Switches(research=False, llm_review=False), record_messages=True)
    hours = [h + H1 for h in data.hours()]
    run = hours[-24 * 75 :]
    for h in run:
        await firm.step(h)
    now = run[-1]
    view = data.view(now)
    rep = firm.last_report
    state = {
        "started_at": run[0].isoformat(),
        "runs": len(run),
        "llm": {"calls": 0, "cost_usd": 0, "name": "none"},
        "decisions": [to_dict(d) for d in firm.decisions][-300:],
        "messages": [to_dict(m) for m in firm.messages][-300:],
        "latest": {
            "ts": rep.ts,
            "research": {},
            "reviews": {k: to_dict(v) for k, v in rep.reviews.items()},
            "tests": {k: to_dict(v) for k, v in rep.tests.items()},
            "risk": rep.risk,
            "decisions": [to_dict(d) for d in rep.decisions],
        }
        if rep
        else {},
    }
    snap = snapshot(cfg, data, view, firm, firm.scanner.scan(view), state, [])
    snap["generated_at"] = now.isoformat()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "snapshot.json").write_text(json.dumps(snap, default=_json_default))
    print("sample snapshot:", len(firm.decisions), "decisions,", len(firm.broker.trades), "trades")


class Args:
    data = None
    out = "/tmp/sample-bt"
    start = None
    end = None
    warmup_days = 400
    seed = 0


if __name__ == "__main__":
    asyncio.run(live_sample())
    asyncio.run(main_async(Args()))
    shutil.copy("/tmp/sample-bt/backtest.json", OUT / "backtest.json")

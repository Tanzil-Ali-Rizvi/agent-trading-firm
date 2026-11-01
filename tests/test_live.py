import asyncio
import json

import pandas as pd

from tradingfloor.config import FloorConfig
from tradingfloor.live import run_live
from tradingfloor.llm import ScriptedLLM
from tradingfloor.market import synthetic

CFG = FloorConfig()


def test_live_runs_resume_from_state(tmp_path):
    h1 = synthetic(CFG.universe, hours=24 * 450, seed=5)
    llm = ScriptedLLM(default={"verdict": "approve", "confidence": 80, "thesis": "trend intact", "risks": []})
    t1 = pd.Timestamp("2025-03-01 08:00", tz="UTC")
    snap = asyncio.run(run_live(tmp_path, tmp_path / "c.gz", llm=llm, now=t1, h1=h1, headlines=[]))
    assert snap["as_of"] == t1.isoformat() and snap["runs"] == 1
    assert len(snap["scanner"]) == 20 and "BTC" in snap["charts"]
    # six hours later: the second run processes the missed hours and resumes the same book
    t2 = t1 + pd.Timedelta(hours=6)
    snap2 = asyncio.run(run_live(tmp_path, tmp_path / "c.gz", llm=llm, now=t2, h1=h1, headlines=[]))
    st = json.loads((tmp_path / "state.json").read_text())
    assert snap2["runs"] == 2 and st["last_processed"] == t2.isoformat()
    assert len(st["portfolio"]["equity"]) == 7  # one mark per processed hour
    json.dumps(snap2)  # the dashboard payload is plain JSON


def test_live_without_llm_is_rules_only(tmp_path):
    h1 = synthetic(CFG.universe, hours=24 * 450, seed=5)
    snap = asyncio.run(run_live(tmp_path, tmp_path / "c.gz", llm=None, now=pd.Timestamp("2025-03-01 08:00", tz="UTC"),
                                h1=h1, headlines=[]))  # fmt: skip
    assert snap["llm"]["name"] == "none"

"""Command line: `tradingfloor download | backtest | live | llm-ablation | serve`."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="tradingfloor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="download hourly candles from Coinbase")
    d.add_argument("--start", required=True)
    d.add_argument("--end", default=None)
    d.add_argument("--out", default="data/market.json.gz")

    b = sub.add_parser("backtest", help="run the backtest, ablations and benchmarks")
    b.add_argument("--data")
    b.add_argument("--out", default="results")
    b.add_argument("--start")
    b.add_argument("--end")
    b.add_argument("--warmup-days", type=int, default=60)
    b.add_argument("--seed", type=int, default=0)

    lv = sub.add_parser("live", help="run one live paper-trading cycle")
    lv.add_argument("--state-dir", default="state")
    lv.add_argument("--cache", default=".cache/market.json.gz")

    a = sub.add_parser("llm-ablation", help="does the LLM review improve the setups it approves?")
    a.add_argument("--data", required=True)
    a.add_argument("--out", default="results")
    a.add_argument("--start", required=True)
    a.add_argument("--max-setups", type=int, default=150)

    s = sub.add_parser("serve", help="serve the dashboard API locally")
    s.add_argument("--state-dir", default="state")
    s.add_argument("--results", default="results")
    s.add_argument("--port", type=int, default=8000)

    args = ap.parse_args(argv)
    if args.cmd == "download":
        from .config import UNIVERSE
        from .market import download, save

        start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
        end = (
            datetime.fromisoformat(args.end).replace(tzinfo=UTC)
            if args.end
            else datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        )
        h1 = asyncio.run(download(UNIVERSE, start, end))
        save(h1, Path(args.out))
        print(json.dumps({c: len(df) for c, df in h1.items()}))
    elif args.cmd == "backtest":
        from .backtest import main_async

        asyncio.run(main_async(args))
    elif args.cmd == "live":
        from .live import run_live

        snap = asyncio.run(run_live(Path(args.state_dir), Path(args.cache)))
        p = snap["portfolio"]
        print(f"as of {snap['as_of']}: equity ${p['equity']:,.2f}, {len(p['positions'])} positions, "
              f"{len(snap['latest'].get('decisions', []))} ideas in the latest cycle, LLM {snap['llm']['name']}")  # fmt: skip
    elif args.cmd == "llm-ablation":
        from .ablation import main_async as ablation

        asyncio.run(ablation(args))
    elif args.cmd == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(Path(args.state_dir), Path(args.results)), host="0.0.0.0", port=args.port)
    else:  # pragma: no cover
        sys.exit(2)


if __name__ == "__main__":
    main()

"""Small read-only API for running the dashboard locally (the hosted dashboard reads the same JSON from GitHub)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware


def create_app(state_dir: Path, results_dir: Path) -> FastAPI:
    app = FastAPI(title="agent-trading-firm", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])

    def read(path: Path) -> dict:
        if not path.exists():
            raise HTTPException(404, f"{path.name} not found; run `tradingfloor live` or `tradingfloor backtest` first")
        return json.loads(path.read_text())

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/snapshot.json")
    def snapshot() -> dict:
        return read(state_dir / "snapshot.json")

    @app.get("/backtest.json")
    def backtest() -> dict:
        return read(results_dir / "backtest.json")

    @app.get("/llm_ablation.json")
    def ablation() -> dict:
        return read(results_dir / "llm_ablation.json")

    return app

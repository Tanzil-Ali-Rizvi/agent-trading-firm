"""Performance metrics shared by the backtest and the live portfolio desk."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .models import Trade

HOURS_PER_YEAR = 24 * 365


def equity_metrics(equity: pd.Series) -> dict[str, float]:
    """`equity` is an hourly series of account value."""
    equity = equity.dropna()
    if len(equity) < 2:
        return {"total_return": 0.0, "cagr": 0.0, "sharpe": 0.0, "sortino": 0.0, "max_drawdown": 0.0, "calmar": 0.0,
                "volatility": 0.0}  # fmt: skip
    rets = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).total_seconds() / (3600 * HOURS_PER_YEAR)
    total = equity.iloc[-1] / equity.iloc[0] - 1
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0
    sd = rets.std()
    down = rets[rets < 0].std()
    sharpe = rets.mean() / sd * math.sqrt(HOURS_PER_YEAR) if sd > 0 else 0.0
    sortino = rets.mean() / down * math.sqrt(HOURS_PER_YEAR) if down and down > 0 else 0.0
    dd = (equity / equity.cummax() - 1).min()
    return {
        "total_return": float(total),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_drawdown": float(dd),
        "calmar": float(cagr / abs(dd)) if dd < 0 else 0.0,
        "volatility": float(sd * math.sqrt(HOURS_PER_YEAR)),
    }


def trade_metrics(trades: list[Trade]) -> dict[str, float]:
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "avg_r": 0.0, "profit_factor": 0.0, "avg_win_r": 0.0, "avg_loss_r": 0.0,
                "best_r": 0.0, "worst_r": 0.0}  # fmt: skip
    r = np.array([t.r_multiple for t in trades])
    pnl = np.array([t.pnl for t in trades])
    gains, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    return {
        "trades": len(trades),
        "win_rate": float((pnl > 0).mean()),
        "avg_r": float(r.mean()),
        "profit_factor": float(gains / losses) if losses > 0 else float("inf") if gains > 0 else 0.0,
        "avg_win_r": float(r[r > 0].mean()) if (r > 0).any() else 0.0,
        "avg_loss_r": float(r[r <= 0].mean()) if (r <= 0).any() else 0.0,
        "best_r": float(r.max()),
        "worst_r": float(r.min()),
    }

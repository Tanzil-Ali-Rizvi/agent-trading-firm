"""Floor 05, risk: position size, exposure and loss limits. A good story still needs limits.

No LLM here on purpose: these checks must behave the same way every time. Each failed check carries a severity:
"reject" means the idea itself is unacceptable (too illiquid, too volatile, poor reward/risk); "wait" means the idea
may be fine but the book can't take it right now (risk-off market, too many positions, daily loss limit hit).
"""

from __future__ import annotations

import math

import pandas as pd

from ..config import FloorConfig
from ..market import MarketView
from ..models import Check, RiskDecision, Setup
from .executor import PaperBroker


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def usd(x: float) -> str:
    return f"${x:,.0f}" if abs(x) >= 1000 else f"${x:,.2f}"


class RiskManager:
    name = "risk"

    def __init__(self, cfg: FloorConfig):
        self.cfg = cfg

    def evaluate(self, setup: Setup, view: MarketView, broker: PaperBroker, enabled: bool = True) -> RiskDecision:
        r = self.cfg.risk
        f = view.latest(setup.coin)
        equity = broker.equity(broker.marks(view))
        checks: list[Check] = []

        def add(name: str, ok: bool, value: str, limit: str, severity: str = "reject") -> None:
            checks.append(Check(name, bool(ok), value, limit, severity))  # type: ignore[arg-type]

        # --- is the idea acceptable at all?
        vol_usd = float(f["volume_usd_24h"]) if f is not None else 0.0
        add("Liquidity (24h volume)", vol_usd >= r.min_volume_usd_24h, usd(vol_usd), f">= {usd(r.min_volume_usd_24h)}")
        atr_pct = setup.atr / setup.entry
        add("Volatility (4h ATR)", atr_pct <= r.max_atr_pct, pct(atr_pct), f"<= {pct(r.max_atr_pct)}")
        add("Reward / risk", setup.reward_risk >= r.min_reward_risk, f"1:{setup.reward_risk:.1f}",
            f">= 1:{r.min_reward_risk:.0f}")  # fmt: skip

        # --- can the book take it right now?
        btc = view.latest("BTC")
        if r.regime_filter and btc is not None and not math.isnan(btc["ema_slow"]):
            above = btc["close"] > btc["ema_slow"]
            add("Market regime (BTC > EMA200)", above, "risk-on" if above else "risk-off", "risk-on", "wait")
        held = setup.coin in broker.positions or setup.coin in broker.pending
        add("Not already holding", not held, "held" if held else "flat", "flat", "wait")
        n_open = len(broker.positions) + len(broker.pending)
        add("Open positions", n_open < r.max_open_positions, str(n_open), f"< {r.max_open_positions}", "wait")
        last_stop = broker.last_stop_out.get(setup.coin)
        if last_stop is not None:
            hours = (view.now - pd.Timestamp(last_stop)).total_seconds() / 3600
            need = r.cooldown_bars_after_stop * self.cfg.decision_hours
            add("Cooldown after stop-out", hours >= need, f"{hours:.0f}h", f">= {need}h", "wait")
        day_pnl = equity / broker.day_start_equity - 1 if broker.day_start_equity else 0.0
        add("Daily loss limit", day_pnl > -r.daily_loss_limit, pct(day_pnl), f"> -{pct(r.daily_loss_limit)}", "wait")

        # --- sizing: risk a fixed share of equity between entry and stop, capped by notional and cash
        risk_per_unit = setup.entry - setup.stop
        units = (equity * r.risk_per_trade) / risk_per_unit if risk_per_unit > 0 else 0.0
        cap = min(equity * r.max_position_pct, broker.cash * 0.98)
        units = min(units, cap / setup.entry)
        notional = units * setup.entry
        risk_usd = units * risk_per_unit
        open_risk = broker.open_risk() + risk_usd
        add("Total open risk", open_risk <= equity * r.max_total_open_risk + 1e-9, pct(open_risk / equity),
            f"<= {pct(r.max_total_open_risk)}", "wait")  # fmt: skip
        add("Position size", notional >= r.min_notional_usd, f"{usd(notional)} ({pct(notional / equity)})",
            f"{usd(r.min_notional_usd)} to {pct(r.max_position_pct)} of equity", "wait")  # fmt: skip

        if not enabled:  # ablation "no risk floor": size every trade at the cap, skip all checks except holding
            units = min(equity * r.max_position_pct, broker.cash * 0.98) / setup.entry
            ok = units * setup.entry >= r.min_notional_usd and not held
            return RiskDecision(setup.coin, ok, checks, units, units * setup.entry, units * risk_per_unit,
                                "risk floor disabled")  # fmt: skip

        failed = [c for c in checks if not c.passed]
        approved = not failed
        return RiskDecision(
            coin=setup.coin,
            approved=approved,
            checks=checks,
            units=units if approved else 0.0,
            notional=notional if approved else 0.0,
            risk_usd=risk_usd if approved else 0.0,
            reason="within all limits"
            if approved
            else "; ".join(f"{c.name} {c.value} (limit {c.limit})" for c in failed),
        )

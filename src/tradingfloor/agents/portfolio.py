"""Portfolio desk: marks the book to market every hour, keeps the equity curve, and raises alerts."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..models import Alert, Fill, Opportunity
from .executor import PaperBroker


class PortfolioDesk:
    name = "portfolio"

    def __init__(self, max_alerts: int = 60):
        self.equity: list[tuple[str, float, float, float]] = []  # ts, equity, cash, exposure
        self.alerts: list[Alert] = []
        self.peak = 0.0
        self._dd_alerted = 0.0
        self.max_alerts = max_alerts

    def record(self, ts: pd.Timestamp, broker: PaperBroker) -> float:
        eq = broker.equity()
        self.equity.append((ts.isoformat(), round(eq, 2), round(broker.cash, 2), round(broker.exposure(), 2)))
        self.peak = max(self.peak, eq)
        dd = eq / self.peak - 1 if self.peak else 0.0
        for level in (0.05, 0.10, 0.15):
            if dd <= -level and self._dd_alerted < level:
                self._dd_alerted = level
                self.alert(ts, "bad", "", f"Drawdown reached -{level * 100:.0f}% from the peak")
        if dd > -0.02:
            self._dd_alerted = 0.0
        return eq

    def on_fills(self, ts: pd.Timestamp, fills: list[Fill]) -> None:
        for f in fills:
            if f.side == "buy":
                self.alert(ts, "info", f.coin, f"Bought {f.units:.4g} {f.coin} at ${f.price:,.4g}")
            else:
                level = "good" if (f.pnl or 0) > 0 else "bad"
                self.alert(
                    ts,
                    level,
                    f.coin,
                    f"Closed {f.coin} ({f.reason}): {'+' if (f.pnl or 0) >= 0 else '-'}${abs(f.pnl or 0):,.2f}",
                )

    def on_scan(self, ts: pd.Timestamp, opps: list[Opportunity]) -> None:
        for o in opps:
            if o.ret_24h >= 0.10:
                self.alert(ts, "warn", o.coin, f"{o.coin} up {o.ret_24h * 100:.0f}% in 24h")
            elif o.ret_24h <= -0.10:
                self.alert(ts, "warn", o.coin, f"{o.coin} down {abs(o.ret_24h) * 100:.0f}% in 24h")
            if o.volume_ratio >= 3:
                self.alert(ts, "info", o.coin, f"{o.coin} volume spike: {o.volume_ratio:.1f}x the 20-bar average")

    def alert(self, ts: pd.Timestamp, level: str, coin: str, text: str) -> None:
        self.alerts.append(Alert(ts.isoformat(), level, coin, text))  # type: ignore[arg-type]
        self.alerts = self.alerts[-self.max_alerts :]

    def series(self) -> pd.Series:
        if not self.equity:
            return pd.Series(dtype=float)
        return pd.Series([e[1] for e in self.equity], index=pd.to_datetime([e[0] for e in self.equity]))

    def to_dict(self) -> dict[str, Any]:
        return {"equity": self.equity, "alerts": [a.__dict__ for a in self.alerts], "peak": self.peak,
                "dd_alerted": self._dd_alerted}  # fmt: skip

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PortfolioDesk:
        p = cls()
        p.equity = [tuple(e) for e in d.get("equity", [])]  # type: ignore[misc]
        p.alerts = [Alert(**a) for a in d.get("alerts", [])]
        p.peak = d.get("peak", 0.0)
        p._dd_alerted = d.get("dd_alerted", 0.0)
        return p

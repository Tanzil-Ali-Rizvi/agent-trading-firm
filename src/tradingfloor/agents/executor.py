"""Agent 5, executor: a paper broker. Fills approved orders at the next bar's open, then manages each position's
stop, breakeven move, trailing stop and target bar by bar, charging fees and slippage on every fill.

Fill rules are deliberately pessimistic:
* entries fill at the *next* hourly open plus slippage, never at the signal bar's close;
* if a bar touches both the stop and the target, the stop is assumed to have been hit first;
* if a bar opens through the stop (a gap), the exit happens at the open, not at the stop price.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from ..config import FloorConfig
from ..market import Bar, MarketView
from ..models import Fill, PendingOrder, Position, RiskDecision, Setup, Trade


class PaperBroker:
    name = "executor"

    def __init__(self, cfg: FloorConfig):
        self.cfg = cfg
        self.cash = cfg.starting_cash
        self.positions: dict[str, Position] = {}
        self.pending: dict[str, PendingOrder] = {}
        self.fills: list[Fill] = []
        self.trades: list[Trade] = []
        self.last_stop_out: dict[str, str] = {}
        self.day = ""
        self.day_start_equity = cfg.starting_cash
        self._last_marks: dict[str, float] = {}

    # ------------------------------------------------------------ valuation
    def marks(self, view: MarketView) -> dict[str, float]:
        for c in self.positions:
            p = view.last_price(c)
            if p is not None:
                self._last_marks[c] = p
        return dict(self._last_marks)

    def equity(self, marks: dict[str, float] | None = None) -> float:
        marks = marks if marks is not None else self._last_marks
        return self.cash + sum(p.units * marks.get(c, p.entry_price) for c, p in self.positions.items())

    def exposure(self, marks: dict[str, float] | None = None) -> float:
        marks = marks if marks is not None else self._last_marks
        return sum(p.units * marks.get(c, p.entry_price) for c, p in self.positions.items())

    def open_risk(self) -> float:
        """Money lost if every open stop is hit (zero for a position whose stop is at or above entry)."""
        risk = sum(p.units * max(0.0, p.entry_price - p.stop) for p in self.positions.values())
        return risk + sum(o.units * o.atr * self.cfg.strategy.stop_atr for o in self.pending.values())

    # ------------------------------------------------------------ orders
    def place(self, setup: Setup, decision: RiskDecision, ts: str) -> PendingOrder:
        order = PendingOrder(setup.coin, decision.units, setup.stop, setup.target, setup.atr, ts)
        self.pending[setup.coin] = order
        return order

    def new_day(self, ts: pd.Timestamp) -> None:
        d = ts.strftime("%Y-%m-%d")
        if d != self.day:
            self.day = d
            self.day_start_equity = self.equity()

    def on_bar(self, coin: str, bar: Bar) -> list[Fill]:
        """Process one closed hourly bar for one coin. Returns the fills it produced."""
        c = self.cfg.costs
        s = self.cfg.strategy
        out: list[Fill] = []
        ts = bar.ts.isoformat()

        order = self.pending.pop(coin, None)
        if order is not None:
            price = bar.open * (1 + c.slippage_rate)
            units = min(order.units, self.cash / (price * (1 + c.fee_rate)))
            # The stop and target were set from the signal close; keep the same distances from the actual fill.
            risk = order.atr * s.stop_atr
            if units * price >= self.cfg.risk.min_notional_usd:
                fee = units * price * c.fee_rate
                self.cash -= units * price + fee
                self.positions[coin] = Position(
                    coin,
                    units,
                    price,
                    ts,
                    price - risk,
                    price - risk,
                    price + s.take_profit_r * risk,
                    order.atr,
                    price,
                    fee,
                )
                f = Fill(ts, coin, "buy", price, units, fee, "entry")
                self.fills.append(f)
                out.append(f)

        pos = self.positions.get(coin)
        if pos is None:
            return out
        exit_price, reason = None, ""
        if bar.low <= pos.stop:
            exit_price = min(bar.open, pos.stop)
            if pos.stop <= pos.initial_stop:
                reason = "stop"
            elif pos.stop < pos.entry_price:
                reason = "trailing stop"
            elif pos.stop == pos.entry_price:
                reason = "breakeven stop"
            else:
                reason = "trailing stop (profit)"
        elif bar.high >= pos.target:
            exit_price, reason = max(bar.open, pos.target), "target"
        if exit_price is not None:
            out.append(self._close(pos, exit_price, ts, reason))
            return out

        # still open: update breakeven and trailing stop using this bar's close
        pos.highest_close = max(pos.highest_close, bar.close)
        r = pos.risk_per_unit
        if bar.close >= pos.entry_price + s.breakeven_r * r:
            pos.stop = max(pos.stop, pos.entry_price)
        pos.stop = max(pos.stop, pos.highest_close - s.trail_atr * pos.atr)
        self._last_marks[coin] = bar.close
        return out

    def close_all(self, view: MarketView, reason: str = "end of test") -> None:
        for coin, pos in list(self.positions.items()):
            p = view.last_price(coin) or pos.entry_price
            self._close(pos, p, view.now.isoformat(), reason)

    def _close(self, pos: Position, price: float, ts: str, reason: str) -> Fill:
        c = self.cfg.costs
        px = price * (1 - c.slippage_rate)
        fee = pos.units * px * c.fee_rate
        self.cash += pos.units * px - fee
        pnl = pos.units * (px - pos.entry_price) - fee - pos.fees_paid
        r_mult = pnl / (pos.units * pos.risk_per_unit) if pos.risk_per_unit > 0 else 0.0
        self.trades.append(Trade(pos.coin, pos.entry_ts, ts, pos.entry_price, px, pos.units, pnl, r_mult, reason))
        if reason == "stop":
            self.last_stop_out[pos.coin] = ts
        del self.positions[pos.coin]
        self._last_marks.pop(pos.coin, None)
        f = Fill(ts, pos.coin, "sell", px, pos.units, fee, reason, pnl)
        self.fills.append(f)
        return f

    # ------------------------------------------------------------ persistence (live mode)
    def to_dict(self) -> dict[str, Any]:
        return {
            "cash": self.cash,
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "pending": {k: asdict(v) for k, v in self.pending.items()},
            "fills": [asdict(f) for f in self.fills[-500:]],
            "trades": [asdict(t) for t in self.trades],
            "last_stop_out": self.last_stop_out,
            "day": self.day,
            "day_start_equity": self.day_start_equity,
            "marks": self._last_marks,
        }

    @classmethod
    def from_dict(cls, cfg: FloorConfig, d: dict[str, Any]) -> PaperBroker:
        b = cls(cfg)
        b.cash = d["cash"]
        b.positions = {k: Position(**v) for k, v in d.get("positions", {}).items()}
        b.pending = {k: PendingOrder(**v) for k, v in d.get("pending", {}).items()}
        b.fills = [Fill(**f) for f in d.get("fills", [])]
        b.trades = [Trade(**t) for t in d.get("trades", [])]
        b.last_stop_out = d.get("last_stop_out", {})
        b.day = d.get("day", "")
        b.day_start_equity = d.get("day_start_equity", cfg.starting_cash)
        b._last_marks = d.get("marks", {})
        return b

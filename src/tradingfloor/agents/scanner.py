"""Floor 01, scanner: ranks the whole universe every 4 hours and sends moves worth investigating up the building."""

from __future__ import annotations

import math

from ..config import FloorConfig
from ..market import MarketView
from ..models import Opportunity


class Scanner:
    name = "scanner"

    def __init__(self, cfg: FloorConfig):
        self.cfg = cfg

    def scan(self, view: MarketView) -> list[Opportunity]:
        rows: list[Opportunity] = []
        for coin in self.cfg.universe:
            f = view.latest(coin)
            if f is None or any(math.isnan(f[k]) for k in ("ema_slow", "rsi", "atr", "ret_7d", "volume_ratio")):
                continue  # not enough history yet
            trend = (
                "up"
                if f["close"] > f["ema_fast"] > f["ema_slow"]
                else "down"
                if f["close"] < f["ema_fast"] < f["ema_slow"]
                else "mixed"
            )
            breakout = bool(f["close"] > f["prior_high"]) if not math.isnan(f["prior_high"]) else False
            reasons = []
            if trend == "up":
                reasons.append("uptrend (price > EMA50 > EMA200)")
            if breakout:
                reasons.append(f"broke the {self.cfg.strategy.breakout_lookback}-bar high")
            if f["volume_ratio"] >= self.cfg.strategy.volume_ratio_min:
                reasons.append(f"volume {f['volume_ratio']:.1f}x average")
            if f["ret_7d"] > 0.10:
                reasons.append(f"+{f['ret_7d'] * 100:.0f}% in 7 days")
            # Score: momentum, trend and participation. Liquidity only filters; it does not add points.
            score = (
                40 * max(min(f["ret_7d"] / 0.25, 1), -1)
                + 20 * max(min(f["ret_24h"] / 0.08, 1), -1)
                + (20 if trend == "up" else -20 if trend == "down" else 0)
                + (10 if breakout else 0)
                + 10 * min(f["volume_ratio"] / 3, 1)
            )
            rows.append(
                Opportunity(
                    coin=coin,
                    price=float(f["close"]),
                    ret_24h=float(f["ret_24h"]),
                    ret_7d=float(f["ret_7d"]),
                    volume_usd_24h=float(f["volume_usd_24h"]),
                    atr_pct=float(f["atr_pct"]),
                    rsi=float(f["rsi"]),
                    trend=trend,
                    volume_ratio=float(f["volume_ratio"]),
                    breakout=breakout,
                    score=round(float(score), 1),
                    reasons=reasons,
                )
            )
        return sorted(rows, key=lambda o: o.score, reverse=True)

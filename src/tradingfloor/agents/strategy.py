"""Floor 03, strategy: turns an idea into clear rules (entry, exit, invalidation), then asks an LLM for a second opinion.

The setup itself (entry, stop, target) is computed by rules. The LLM review can approve or veto it and writes the
thesis shown on the dashboard, but it cannot move the stop, the target or the size.
"""

from __future__ import annotations

import json
import math

from ..config import FloorConfig
from ..llm import LLM
from ..market import MarketView
from ..models import Opportunity, Review, Setup

SYSTEM = """You are the strategist on a risk-controlled crypto trading desk that only takes long spot positions.
A rules engine has proposed a trend-following breakout entry. Your job is a second opinion: approve it, or
reject it if the evidence looks weak (exhausted move, failing momentum, poor reward for the risk, choppy trend).
You cannot change the entry, stop, target or size. Judge only the numbers provided.

Reply with JSON only:
{"verdict": "approve" | "reject", "confidence": <integer 0-100>, "thesis": "<max 40 words>",
 "risks": ["<max 3 short items>"]}"""


RULE_TEXT = {
    "uptrend": "uptrend (close > EMA50 > EMA200)",
    "breakout": "close above the 20-bar high",
    "momentum": "MACD histogram > 0",
    "volume": "volume >= 1.5x average",
    "rsi_in_range": "RSI between 55 and 80",
}


def signals_for(f, s) -> dict[str, bool]:
    """The entry rules, for one row of 4h features. `signal_mask` is the same rules for a whole history."""
    return {
        "uptrend": bool(f["close"] > f["ema_fast"] > f["ema_slow"]),
        "breakout": bool(f["close"] > f["prior_high"]),
        "momentum": bool(f["macd_hist"] > 0),
        "volume": bool(f["volume_ratio"] >= s.volume_ratio_min),
        "rsi_in_range": bool(s.rsi_min <= f["rsi"] <= s.rsi_max),
    }


def signal_mask(f, s):
    return (
        (f["close"] > f["ema_fast"])
        & (f["ema_fast"] > f["ema_slow"])
        & (f["close"] > f["prior_high"])
        & (f["macd_hist"] > 0)
        & (f["volume_ratio"] >= s.volume_ratio_min)
        & (f["rsi"] >= s.rsi_min)
        & (f["rsi"] <= s.rsi_max)
    )


class Strategy:
    name = "strategy"

    def __init__(self, cfg: FloorConfig, llm: LLM | None = None):
        self.cfg = cfg
        self.llm = llm

    # ------------------------------------------------------------ rules
    def setup_for(self, opp: Opportunity, view: MarketView) -> tuple[Setup | None, str]:
        """Return the setup, or None and the reason the idea does not meet the entry rules."""
        s = self.cfg.strategy
        f = view.latest(opp.coin)
        if f is None:
            return None, "no data"
        signals = signals_for(f, s)
        missing = [RULE_TEXT[k] for k, ok in signals.items() if not ok]
        if missing:
            return None, "entry rules not met: " + ", ".join(missing)
        entry = float(f["close"])
        atr = float(f["atr"])
        stop = entry - s.stop_atr * atr
        target = entry + s.take_profit_r * (entry - stop)
        conf = int(round(100 * sum(signals.values()) / len(signals)))
        return Setup(
            coin=opp.coin,
            entry=entry,
            stop=stop,
            target=target,
            atr=atr,
            signals=signals,
            indicators={
                "rsi": round(float(f["rsi"]), 1),
                "macd_hist_pct": round(float(f["macd_hist"]) / entry * 100, 3),
                "atr_pct": round(float(f["atr_pct"]) * 100, 2),
                "vs_ema50_pct": round((entry / float(f["ema_fast"]) - 1) * 100, 2),
                "vs_ema200_pct": round((entry / float(f["ema_slow"]) - 1) * 100, 2),
                "volume_ratio": round(float(f["volume_ratio"]), 2),
                "ret_24h_pct": round(float(f["ret_24h"]) * 100, 2),
                "ret_7d_pct": round(float(f["ret_7d"]) * 100, 2),
            },
            rule_confidence=conf,
        ), "entry rules met"

    # ------------------------------------------------------------ LLM review
    def prompt(self, setup: Setup, view: MarketView, anonymize: bool) -> str:
        hist = view.last_4h(setup.coin, 30)
        base = float(hist["close"].iloc[0]) if len(hist) else setup.entry
        closes = [round(float(c) / base * 100, 1) for c in hist["close"]]
        btc = view.latest("BTC")
        regime = None
        if btc is not None and not math.isnan(btc["ema_slow"]):
            regime = "BTC above its 200-bar EMA" if btc["close"] > btc["ema_slow"] else "BTC below its 200-bar EMA"
        risk_pct = (setup.entry - setup.stop) / setup.entry * 100
        payload = {
            "asset": "Asset A" if anonymize else setup.coin,
            "timeframe": "4-hour bars",
            "last_30_closes_indexed_to_100": closes,
            "indicators": setup.indicators,
            "market_regime": regime,
            "proposal": {
                "entry": "next bar open",
                "stop_distance_pct": round(risk_pct, 2),
                "target_distance_pct": round(risk_pct * self.cfg.strategy.take_profit_r, 2),
                "reward_to_risk": round(setup.reward_risk, 2),
            },
        }
        return "Proposed setup (data only):\n" + json.dumps(payload)

    async def review(self, setup: Setup, view: MarketView, anonymize: bool = False) -> Review:
        if self.llm is None:
            return Review(setup.coin, "skipped", setup.rule_confidence, rules_thesis(setup), [], model="rules only")
        res = await self.llm.complete_json(SYSTEM, self.prompt(setup, view, anonymize), max_tokens=1200)
        if not res.ok or res.data is None:
            return Review(
                setup.coin, "unavailable", 0, f"LLM review failed: {res.error}", [], res.model, res.cost_usd,
                res.latency_ms,
            )  # fmt: skip
        return validate_review(setup.coin, res.data, res.model, res.cost_usd, res.latency_ms)

    def would_veto(self, review: Review) -> bool:
        """The LLM's judgement, independent of whether the firm lets it act on it."""
        if review.verdict == "skipped":
            return False
        if review.verdict == "unavailable":
            return self.cfg.llm.fail_closed
        return review.verdict == "reject" or review.confidence < self.cfg.llm.veto_confidence_below

    def vetoes(self, review: Review) -> bool:
        """Whether the review actually blocks the trade (only in "veto" mode)."""
        return self.cfg.llm.review_mode == "veto" and self.would_veto(review)


def validate_review(coin: str, d: dict, model: str = "", cost: float = 0.0, latency: float = 0.0) -> Review:
    """Untrusted model output -> a well-formed Review. Unknown verdicts count as 'unavailable'."""
    verdict = str(d.get("verdict", "")).strip().lower()
    if verdict not in ("approve", "reject"):
        return Review(coin, "unavailable", 0, "LLM returned an invalid verdict", [], model, cost, latency)
    try:
        conf = int(float(d.get("confidence", 0)))
    except (TypeError, ValueError):
        conf = 0
    risks = d.get("risks") if isinstance(d.get("risks"), list) else []
    return Review(
        coin=coin,
        verdict=verdict,  # type: ignore[arg-type]
        confidence=max(0, min(100, conf)),
        thesis=str(d.get("thesis", ""))[:400],
        risks=[str(r)[:120] for r in risks[:3]],
        model=model,
        cost_usd=cost,
        latency_ms=latency,
    )


def rules_thesis(s: Setup) -> str:
    i = s.indicators
    return (
        f"Breakout above the 20-bar high in an uptrend ({i['vs_ema200_pct']:+.1f}% vs EMA200), RSI {i['rsi']:.0f}, "
        f"volume {i['volume_ratio']:.1f}x average. Stop {i['atr_pct'] * 2:.1f}% below, target {s.reward_risk:.0f}R."
    )

"""The firm: six floors that every idea climbs, plus the execution and portfolio desks.

    01 scanner -> 02 research -> 03 strategy -> 04 testing -> 05 risk -> 06 control -> execution desk -> portfolio desk

`TradingFirm.step(now)` is the single code path for both the backtest and live paper trading. It is called once per
hour boundary: the execution desk processes the hourly bar that just closed, the portfolio desk marks the book, and
on every completed 4-hour bar the floors run a decision cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .agents.control import Control
from .agents.executor import PaperBroker
from .agents.portfolio import PortfolioDesk
from .agents.research import Research
from .agents.risk import RiskManager
from .agents.scanner import Scanner
from .agents.strategy import Strategy
from .agents.testing import Testing
from .config import FloorConfig
from .llm import LLM
from .market import H1, MarketData
from .models import Decision, FloorVerdict, Message, Opportunity, ResearchNote, Review, TestReport, to_dict


@dataclass
class Switches:
    """Which floors are active. The backtest turns floors off one at a time to measure what each adds."""

    research: bool = True
    testing: bool = True
    risk: bool = True
    llm_review: bool = True
    anonymize_llm: bool = False  # backtest: hide coin names and dates so the model can't use hindsight
    max_ideas: int = 5


@dataclass
class CycleReport:
    ts: str
    opportunities: list[Opportunity] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    research: dict[str, ResearchNote] = field(default_factory=dict)
    reviews: dict[str, Review] = field(default_factory=dict)
    tests: dict[str, TestReport] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)


class TradingFirm:
    def __init__(
        self,
        cfg: FloorConfig,
        data: MarketData,
        broker: PaperBroker | None = None,
        portfolio: PortfolioDesk | None = None,
        llm: LLM | None = None,
        switches: Switches | None = None,
        headlines: list[dict[str, str]] | None = None,
        record_messages: bool = False,
        trading_enabled: bool = True,
    ):
        self.cfg = cfg
        self.data = data
        self.sw = switches or Switches()
        self.broker = broker or PaperBroker(cfg)
        self.portfolio = portfolio or PortfolioDesk()
        self.scanner = Scanner(cfg)
        self.research = Research(llm if self.sw.llm_review else None)
        self.strategy = Strategy(cfg, llm if self.sw.llm_review else None)
        self.testing = Testing(cfg, data)
        self.risk = RiskManager(cfg)
        self.control = Control(trading_enabled)
        self.headlines = headlines
        self.record_messages = record_messages
        self.messages: list[Message] = []
        self.decisions: list[Decision] = []
        self.last_report: CycleReport | None = None
        self.llm_calls = 0
        self.llm_cost = 0.0

    # ------------------------------------------------------------------ messaging (for the dashboard)
    def say(self, now: pd.Timestamp, sender: str, receiver: str, kind: str, text: str, **data: Any) -> None:
        if self.record_messages:
            self.messages.append(Message(now.isoformat(), sender, receiver, kind, text, to_dict(data)))  # type: ignore[arg-type]

    # ------------------------------------------------------------------ the clock
    async def step(self, now: pd.Timestamp, allow_decide: bool = True) -> CycleReport | None:
        """Advance to hour boundary `now`. Live catch-up runs pass allow_decide=False for hours already in the past."""
        self.broker.new_day(now - H1)
        bar_start = now - H1
        for coin in set(self.broker.positions) | set(self.broker.pending):
            bar = self.data.h1_bar(coin, bar_start)
            if bar is None:
                continue
            fills = self.broker.on_bar(coin, bar)
            for f in fills:
                verb = "bought" if f.side == "buy" else f"sold ({f.reason})"
                pnl = f", P&L {f.pnl:+,.2f}" if f.pnl is not None else ""
                self.say(now, "executor", "portfolio", "fill", f"{verb} {f.units:.4g} {coin} at {f.price:,.6g}{pnl}")
            self.portfolio.on_fills(now, fills)
        self.broker.marks(self.data.view(now))
        self.portfolio.record(now, self.broker)
        if allow_decide and now.hour % self.cfg.decision_hours == 0:
            return await self.decide(now)
        return None

    # ------------------------------------------------------------------ one idea up the building
    async def decide(self, now: pd.Timestamp) -> CycleReport:
        view = self.data.view(now)
        ts = now.isoformat()
        rep = CycleReport(ts)
        opps = self.scanner.scan(view)
        rep.opportunities = opps
        self.portfolio.on_scan(now, opps[:10])
        ideas = [o for o in opps if o.trend == "up" and o.breakout][: self.sw.max_ideas]
        self.say(now, "scanner", "research", "scan",
                 f"scanned {len(opps)} coins; {len(ideas)} moves worth investigating"
                 + (": " + ", ".join(i.coin for i in ideas) if ideas else ""))  # fmt: skip

        for idea in ideas:
            floors = [FloorVerdict("scanner", "pass", "; ".join(idea.reasons) or "ranked candidate")]
            setup, risk, thesis = None, None, ""

            # 02 research
            if self.sw.research and self.headlines is not None:
                note = await self.research.assess(idea.coin, self.headlines)
                rep.research[idea.coin] = note
                self._llm(note.model, note.cost_usd)
                floors.append(FloorVerdict(
                    "research", "reject" if note.blocking else "pass",
                    ("red flags: " + "; ".join(note.red_flags)) if note.blocking else note.summary,
                ))  # fmt: skip
                self.say(now, "research", "strategy", "research", f"{idea.coin}: {note.summary}")
            else:
                floors.append(FloorVerdict("research", "pass", "news check not run (backtest)"))

            # 03 strategy: rules first, then the LLM's second opinion
            if floors[-1].status == "pass":
                setup, why = self.strategy.setup_for(idea, view)
                if setup is None:
                    floors.append(FloorVerdict("strategy", "reject", why))
                else:
                    review = await self.strategy.review(setup, view, anonymize=self.sw.anonymize_llm)
                    rep.reviews[idea.coin] = review
                    self._llm(review.model, review.cost_usd)
                    thesis = review.thesis
                    if self.strategy.vetoes(review):
                        status = "wait" if review.verdict == "unavailable" else "reject"
                        floors.append(FloorVerdict("strategy", status, f"LLM review {review.verdict} "
                                                   f"({review.confidence}): {review.thesis}"))  # fmt: skip
                    else:
                        floors.append(FloorVerdict(
                            "strategy", "pass",
                            f"entry next open ~{setup.entry:,.6g}, stop {setup.stop:,.6g}, target {setup.target:,.6g}"
                            f" (1:{setup.reward_risk:.1f}); "
                            + (
                                f"LLM opinion {review.verdict} ({review.confidence}), advisory only"
                                if self.cfg.llm.review_mode == "advisory" and review.verdict not in ("skipped",)
                                else f"review {review.verdict} ({review.confidence})"
                            ),
                        ))  # fmt: skip
                    self.say(now, "strategy", "testing", "setup", f"{idea.coin}: {thesis}")

            # 04 testing
            if floors[-1].status == "pass" and setup is not None:
                if self.sw.testing:
                    tr = self.testing.evaluate(idea.coin, now)
                    rep.tests[idea.coin] = tr
                    floors.append(FloorVerdict("testing", tr.status, tr.reason))
                    self.say(now, "testing", "risk", "test", f"{idea.coin}: {tr.reason}")
                else:
                    floors.append(FloorVerdict("testing", "pass", "testing floor disabled (ablation)"))

            # 05 risk
            if floors[-1].status == "pass" and setup is not None:
                risk = self.risk.evaluate(setup, view, self.broker, enabled=self.sw.risk)
                rep.risk[idea.coin] = to_dict(risk)
                if risk.approved:
                    floors.append(FloorVerdict("risk", "pass", f"size {risk.units:.4g} {idea.coin} "
                                               f"(${risk.notional:,.0f}), risking ${risk.risk_usd:,.2f}"))  # fmt: skip
                else:
                    sev = "reject" if any(not c.passed and c.severity == "reject" for c in risk.checks) else "wait"
                    floors.append(FloorVerdict("risk", sev, risk.reason))
                self.say(now, "risk", "control", "risk", f"{idea.coin}: {floors[-1].summary}")

            # 06 control
            decision = self.control.decide(ts, idea.coin, idea.price, floors, setup, risk, thesis)
            rep.decisions.append(decision)
            self.decisions.append(decision)
            self.say(now, "control", "executor" if decision.decision == "trade" else "all", "decision",
                     f"{idea.coin}: {decision.decision.upper()} ({decision.reason})")  # fmt: skip
            if decision.decision == "trade" and setup is not None and risk is not None:
                self.broker.place(setup, risk, ts)

        self.last_report = rep
        return rep

    def _llm(self, model: str, cost: float) -> None:
        if model and model not in ("rules only", ""):
            self.llm_calls += 1
            self.llm_cost += cost

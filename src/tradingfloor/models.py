"""Messages the agents pass to each other. Everything is a plain dataclass so it serialises to JSON for the dashboard."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

AgentName = Literal["scanner", "research", "strategy", "testing", "risk", "control", "executor", "portfolio"]
Status = Literal["pass", "wait", "reject"]


def to_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, float):
        return round(obj, 8)
    return obj


@dataclass
class Message:
    ts: str
    sender: AgentName
    receiver: AgentName | Literal["all"]
    kind: str
    text: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Opportunity:
    coin: str
    price: float
    ret_24h: float
    ret_7d: float
    volume_usd_24h: float
    atr_pct: float
    rsi: float
    trend: Literal["up", "down", "mixed"]
    volume_ratio: float
    breakout: bool
    score: float
    reasons: list[str]


@dataclass
class Setup:
    coin: str
    entry: float  # reference price (last close); the fill happens at the next bar's open
    stop: float
    target: float
    atr: float
    signals: dict[str, bool]
    indicators: dict[str, float]
    rule_confidence: int  # 0-100, from the share of confirming signals

    @property
    def reward_risk(self) -> float:
        return (self.target - self.entry) / max(self.entry - self.stop, 1e-12)


@dataclass
class Review:
    """The strategy floor's LLM review of a setup. It can only veto, never enlarge a trade."""

    coin: str
    verdict: Literal["approve", "reject", "unavailable", "skipped"]
    confidence: int
    thesis: str
    risks: list[str]
    model: str = ""
    cost_usd: float = 0.0
    latency_ms: float = 0.0


@dataclass
class ResearchNote:
    coin: str
    sentiment: float  # -1 .. 1
    headlines: list[dict[str, str]]
    catalysts: list[str]
    red_flags: list[str]
    counterpoints: list[str]
    summary: str
    blocking: bool = False
    model: str = ""
    cost_usd: float = 0.0


@dataclass
class Check:
    name: str
    passed: bool
    value: str
    limit: str
    severity: Literal["wait", "reject"] = "reject"  # what a failure means: try later, or drop the idea


@dataclass
class RiskDecision:
    coin: str
    approved: bool
    checks: list[Check]
    units: float = 0.0
    notional: float = 0.0
    risk_usd: float = 0.0
    reason: str = ""


@dataclass
class Position:
    coin: str
    units: float
    entry_price: float
    entry_ts: str
    stop: float
    initial_stop: float
    target: float
    atr: float
    highest_close: float
    fees_paid: float = 0.0

    @property
    def risk_per_unit(self) -> float:
        return self.entry_price - self.initial_stop


@dataclass
class PendingOrder:
    coin: str
    units: float
    stop: float
    target: float
    atr: float
    placed_ts: str


@dataclass
class Fill:
    ts: str
    coin: str
    side: Literal["buy", "sell"]
    price: float
    units: float
    fee: float
    reason: str
    pnl: float | None = None


@dataclass
class Trade:
    coin: str
    entry_ts: str
    exit_ts: str
    entry_price: float
    exit_price: float
    units: float
    pnl: float  # after fees
    r_multiple: float
    exit_reason: str


@dataclass
class Alert:
    ts: str
    level: Literal["info", "good", "warn", "bad"]
    coin: str
    text: str


@dataclass
class TestReport:
    """Floor 04: how this exact rule did on this coin's own past, using only trades that had finished by now."""

    coin: str
    status: Status
    trades: int
    win_rate: float
    expectancy_r: float  # average result per trade in units of initial risk, after fees and slippage
    pooled_trades: int
    pooled_expectancy_r: float
    basis: Literal["coin", "universe", "none"]
    reason: str
    recent: list[float] = field(default_factory=list)  # last few R results, for the dashboard


@dataclass
class FloorVerdict:
    floor: str
    status: Status
    summary: str


@dataclass
class Decision:
    """Floor 06: the final call for one idea, with the verdict of every floor it passed through."""

    ts: str
    coin: str
    decision: Literal["trade", "wait", "reject"]
    reason: str
    floors: list[FloorVerdict]
    price: float = 0.0
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    units: float = 0.0
    notional: float = 0.0
    thesis: str = ""

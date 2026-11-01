"""Floor 06, control: the final decision, which can be "wait".

Control does not re-analyse anything. It reads the verdict of every floor the idea passed through, applies the
firm-wide switches (paper trading only, a kill switch), and writes a decision log entry that explains itself.
An idea stops at the first floor that does not pass it: "reject" drops it, "wait" means it may come back.
"""

from __future__ import annotations

from ..models import Decision, FloorVerdict, RiskDecision, Setup


class Control:
    name = "control"

    def __init__(self, trading_enabled: bool = True):
        self.trading_enabled = trading_enabled  # kill switch: when off, every idea ends as "wait"

    def decide(
        self,
        ts: str,
        coin: str,
        price: float,
        floors: list[FloorVerdict],
        setup: Setup | None = None,
        risk: RiskDecision | None = None,
        thesis: str = "",
    ) -> Decision:
        stopped = next((f for f in floors if f.status != "pass"), None)
        if stopped is not None:
            return Decision(ts, coin, stopped.status, f"{stopped.floor}: {stopped.summary}", floors, price,
                            thesis=thesis)  # fmt: skip
        if not self.trading_enabled:
            floors = [*floors, FloorVerdict("control", "wait", "kill switch is on")]
            return Decision(ts, coin, "wait", "control: kill switch is on", floors, price, thesis=thesis)
        assert setup is not None and risk is not None
        floors = [*floors, FloorVerdict("control", "pass", "all floors passed; sent to the paper execution desk")]
        return Decision(
            ts, coin, "trade", "all floors passed", floors, price, setup.entry, setup.stop, setup.target,
            risk.units, risk.notional, thesis,
        )  # fmt: skip

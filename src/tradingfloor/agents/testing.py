"""Floor 04, testing: test the rules before trusting them. Fees, slippage, unseen data.

For every coin, the exact entry rule is replayed over its own history: enter at the next bar's open, the same stop,
breakeven, trailing stop and target as the live executor, with fees and slippage on both sides, one trade at a time.
Each replayed trade is stamped with the time it *finished*. When an idea arrives at time `now`, only trades that
had finished before `now` count, so the floor never uses an outcome it could not have known yet.

Verdicts:
* pass   - at least 8 finished trades on this coin in the last year, averaging at least +0.10R after costs
           (or, with fewer coin trades, at least 30 across the universe averaging at least +0.10R);
* reject - enough trades on this coin, and they lost money after costs;
* wait   - not enough evidence either way.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import FloorConfig
from ..market import H4, MarketData
from ..models import TestReport
from .strategy import signal_mask


@dataclass
class _Replays:
    entry_ts: np.ndarray  # datetime64[ns, UTC] as int64
    done_ts: np.ndarray
    r: np.ndarray


class Testing:
    name = "testing"
    __test__ = False  # not a pytest test class

    def __init__(self, cfg: FloorConfig, data: MarketData):
        self.cfg = cfg
        self.replays: dict[str, _Replays] = {c: self._replay(f) for c, f in data.h4.items()}

    def _replay(self, f: pd.DataFrame) -> _Replays:
        mask = signal_mask(f, self.cfg.strategy).to_numpy()
        arr = arrays(f)
        idx = pd.DatetimeIndex(f.index).as_unit("ns").asi8
        entries, dones, rs = [], [], []
        i = 0
        while i < len(f) - 1:
            if not mask[i]:
                i += 1
                continue
            out = replay_trade(arr, i, self.cfg)
            if out is None:  # history ended before the trade finished: outcome unknown
                break
            r, j = out
            entries.append(idx[i + 1])
            dones.append(idx[j] + H4.value)  # the outcome is known once the exit bar has closed
            rs.append(r)
            i = j + 1  # one trade at a time per coin, as in live trading
        return _Replays(np.array(entries, dtype=np.int64), np.array(dones, dtype=np.int64), np.array(rs, dtype=float))

    def _window(self, coin: str, now: pd.Timestamp) -> np.ndarray:
        rp = self.replays.get(coin)
        if rp is None or not len(rp.r):
            return np.array([])
        start = (now - pd.Timedelta(days=self.cfg.testing.lookback_days)).value
        keep = (rp.done_ts <= now.value) & (rp.entry_ts >= start)
        return rp.r[keep]

    def evaluate(self, coin: str, now: pd.Timestamp) -> TestReport:
        t = self.cfg.testing
        r = self._window(coin, now)
        pooled = np.concatenate([self._window(c, now) for c in self.replays]) if self.replays else np.array([])
        n, pn = len(r), len(pooled)
        exp = float(r.mean()) if n else 0.0
        pexp = float(pooled.mean()) if pn else 0.0
        win = float((r > 0).mean()) if n else 0.0
        base = {"coin": coin, "trades": n, "win_rate": round(win, 3), "expectancy_r": round(exp, 3),
                "pooled_trades": pn, "pooled_expectancy_r": round(pexp, 3), "recent": [round(x, 2) for x in r[-8:]]}  # fmt: skip
        if n >= t.min_trades_coin:
            if exp >= t.min_expectancy_r:
                return TestReport(
                    status="pass",
                    basis="coin",
                    reason=f"{n} past trades on {coin}: {exp:+.2f}R each after costs",
                    **base,
                )
            if exp <= 0:
                return TestReport(
                    status="reject",
                    basis="coin",
                    reason=f"rule lost money on {coin}: {n} trades, {exp:+.2f}R each after costs",
                    **base,
                )
            return TestReport(
                status="wait", basis="coin", reason=f"edge on {coin} too thin: {exp:+.2f}R per trade", **base
            )
        if pn >= t.min_trades_pool and pexp >= t.min_expectancy_r:
            return TestReport(status="pass", basis="universe",
                              reason=f"only {n} trades on {coin}; across all coins {pn} trades, {pexp:+.2f}R each", **base)  # fmt: skip
        return TestReport(status="wait", basis="none",
                          reason=f"not enough evidence: {n} trades on {coin}, {pn} across all coins at {pexp:+.2f}R", **base)  # fmt: skip


def arrays(f: pd.DataFrame) -> tuple[np.ndarray, ...]:
    return tuple(f[k].to_numpy() for k in ("open", "high", "low", "close", "atr"))


def replay_trade(arr: tuple[np.ndarray, ...], i: int, cfg: FloorConfig) -> tuple[float, int] | None:
    """Replay one trade signalled at 4h bar i with the executor's rules. Returns (R after costs, exit bar index)."""
    s, c = cfg.strategy, cfg.costs
    o, h, lo, cl, atr = arr
    n = len(o)
    if i + 1 >= n:
        return None
    entry = o[i + 1] * (1 + c.slippage_rate)
    risk = s.stop_atr * atr[i]
    stop, target, best = entry - risk, entry + s.take_profit_r * risk, entry
    last = i + cfg.testing.max_hold_bars
    j, exit_px = i + 1, None
    while j <= min(last, n - 1):
        if lo[j] <= stop:
            exit_px = min(o[j], stop)
        elif h[j] >= target:
            exit_px = max(o[j], target)
        if exit_px is not None:
            break
        best = max(best, cl[j])
        if cl[j] >= entry + s.breakeven_r * risk:
            stop = max(stop, entry)
        stop = max(stop, best - s.trail_atr * atr[i])
        j += 1
    if exit_px is None:
        if last > n - 1:
            return None
        j, exit_px = last, cl[last]
    px = exit_px * (1 - c.slippage_rate)
    pnl = px - entry - c.fee_rate * (entry + px)
    return pnl / risk, j

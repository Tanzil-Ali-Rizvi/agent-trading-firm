"""Market data: download from Coinbase's public API, load/save, synthetic data for tests, and a point-in-time view.

`MarketData.view(now)` is the only way agents see prices. It returns bars that had *closed* by `now`, which is what
keeps the backtest free of look-ahead: an agent deciding at 08:00 sees the 04:00-08:00 bar but nothing after it.
"""

from __future__ import annotations

import asyncio
import gzip
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from .config import StrategyConfig
from .indicators import features_4h, resample_4h

H1 = pd.Timedelta(hours=1)
H4 = pd.Timedelta(hours=4)
COINBASE = "https://api.exchange.coinbase.com"
COLS = ["open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------- download
async def fetch_candles(
    client: httpx.AsyncClient, coin: str, start: datetime, end: datetime, granularity: int = 3600
) -> pd.DataFrame:
    """Hourly candles for COIN-USD between start and end. Coinbase returns at most 300 candles per request."""
    rows: list[list[float]] = []
    step = timedelta(seconds=granularity * 300)
    t = start
    while t < end:
        t2 = min(t + step, end)
        for attempt in range(5):
            r = await client.get(
                f"{COINBASE}/products/{coin}-USD/candles",
                params={"granularity": granularity, "start": t.isoformat(), "end": t2.isoformat()},
            )
            if r.status_code == 429 or r.status_code >= 500:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            rows.extend(r.json())
            break
        else:
            raise RuntimeError(f"{coin}: Coinbase kept failing for {t}..{t2}")
        t = t2
        await asyncio.sleep(0.12)  # stay well under the public rate limit
    if not rows:
        return pd.DataFrame(columns=COLS)
    # Coinbase row format: [time, low, high, open, close, volume], newest first
    df = pd.DataFrame(rows, columns=["time", "low", "high", "open", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.drop_duplicates("time").set_index("time").sort_index()[COLS].astype(float)
    return df[(df.index >= pd.Timestamp(start)) & (df.index < pd.Timestamp(end))]


async def download(coins: list[str], start: datetime, end: datetime) -> dict[str, pd.DataFrame]:
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "agent-trading-firm/0.1"}) as client:
        out = {}
        for coin in coins:
            out[coin] = await fetch_candles(client, coin, start, end)
        return out


def save(h1: dict[str, pd.DataFrame], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        c: {"t": [int(x.timestamp()) for x in df.index], **{k: df[k].round(10).tolist() for k in COLS}}
        for c, df in h1.items()
    }
    with gzip.open(path, "wt") as f:
        json.dump(payload, f)


def load(path: Path) -> dict[str, pd.DataFrame]:
    with gzip.open(path, "rt") as f:
        payload = json.load(f)
    out = {}
    for c, d in payload.items():
        idx = pd.to_datetime(d["t"], unit="s", utc=True)
        out[c] = pd.DataFrame({k: d[k] for k in COLS}, index=idx).astype(float)
    return out


def synthetic(
    coins: list[str], hours: int = 24 * 400, seed: int = 0, start: str = "2024-01-01"
) -> dict[str, pd.DataFrame]:
    """Regime-switching random walks with a shared market factor. For tests and offline development only."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=hours, freq="1h", tz="UTC")
    regime = rng.normal(0, 0.0006, hours // 240 + 1)  # each 10-day block trends up or down a little
    market = rng.normal(np.repeat(regime, 240)[:hours], 0.006)
    out = {}
    for i, c in enumerate(coins):
        beta = 0.7 + 0.6 * rng.random()
        r = beta * market + rng.normal(0, 0.006 + 0.004 * rng.random(), hours)
        close = (10 ** rng.uniform(-1, 4.5)) * np.exp(np.cumsum(r))
        open_ = np.concatenate([[close[0]], close[:-1]])
        wig = np.abs(rng.normal(0, 0.004, hours))
        high = np.maximum(open_, close) * (1 + wig)
        low = np.minimum(open_, close) * (1 - wig)
        vol_usd = 2e6 * (20 - i) * (1 + np.abs(r) * 80) * rng.lognormal(0, 0.3, hours)
        out[c] = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": vol_usd / close}, index=idx
        )
    return out


# ---------------------------------------------------------------- point-in-time view
def _ns(df: pd.DataFrame) -> pd.DataFrame:
    """Store every index at nanosecond resolution (pandas 3 may load seconds or microseconds)."""
    df = df.copy()
    df.index = pd.DatetimeIndex(df.index).as_unit("ns")
    return df


@dataclass
class Bar:
    ts: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketData:
    """Holds 1h bars and 4h features for every coin, computed once. Indicators are causal, so slicing is safe."""

    def __init__(self, h1: dict[str, pd.DataFrame], strategy: StrategyConfig):
        self.h1 = {c: _ns(df.sort_index()) for c, df in h1.items() if len(df)}
        self.h4 = {c: features_4h(resample_4h(df), strategy) for c, df in self.h1.items()}
        self._h1_pos = {c: {ts: i for i, ts in enumerate(df.index)} for c, df in self.h1.items()}
        self._h1_arr = {c: df[COLS].to_numpy() for c, df in self.h1.items()}

    @property
    def coins(self) -> list[str]:
        return list(self.h1)

    def hours(self) -> pd.DatetimeIndex:
        """Every hour boundary at which at least one coin has a bar."""
        idx = sorted(set().union(*[set(df.index) for df in self.h1.values()]))
        return pd.DatetimeIndex(idx)

    def h1_bar(self, coin: str, start: pd.Timestamp) -> Bar | None:
        i = self._h1_pos.get(coin, {}).get(start)
        if i is None:
            return None
        o, h, lo, c, v = self._h1_arr[coin][i]
        return Bar(start, o, h, lo, c, v)

    def view(self, now: pd.Timestamp) -> MarketView:
        return MarketView(self, now)


class MarketView:
    """What an agent may see at time `now`: only bars that have closed."""

    def __init__(self, data: MarketData, now: pd.Timestamp):
        self.data = data
        self.now = now

    def last_4h(self, coin: str, n: int = 1) -> pd.DataFrame:
        f = self.data.h4.get(coin)
        if f is None:
            return pd.DataFrame()
        end = f.index.searchsorted(self.now - H4, side="right")  # bars whose start + 4h <= now
        return f.iloc[max(0, end - n) : end]

    def latest(self, coin: str) -> pd.Series | None:
        df = self.last_4h(coin, 1)
        return None if df.empty else df.iloc[-1]

    def last_price(self, coin: str) -> float | None:
        df = self.data.h1.get(coin)
        if df is None:
            return None
        end = df.index.searchsorted(self.now - H1, side="right")
        return None if end == 0 else float(df["close"].iloc[end - 1])

    def h1_history(self, coin: str, n: int) -> pd.DataFrame:
        df = self.data.h1.get(coin)
        if df is None:
            return pd.DataFrame()
        end = df.index.searchsorted(self.now - H1, side="right")
        return df.iloc[max(0, end - n) : end]


def floor_hour(dt: datetime | None = None) -> pd.Timestamp:
    dt = dt or datetime.now(UTC)
    return (
        pd.Timestamp(dt).tz_convert("UTC").floor("1h")
        if pd.Timestamp(dt).tzinfo
        else pd.Timestamp(dt, tz="UTC").floor("1h")
    )

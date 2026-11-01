"""Technical indicators. All of them are causal: the value at bar t only uses bars 0..t."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(gain.notna())


def macd_hist(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    line = ema(close, fast) - ema(close, slow)
    return line - ema(line, signal)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def resample_4h(h1: pd.DataFrame) -> pd.DataFrame:
    """1-hour bars to 4-hour bars aligned to 00:00, 04:00 ... UTC. A bar is labelled by its start time."""
    out = h1.resample("4h", label="left", closed="left", origin="epoch").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["close"])


def features_4h(h4: pd.DataFrame, s) -> pd.DataFrame:
    """Add the columns the scanner and strategy floors read. `s` is a StrategyConfig."""
    f = h4.copy()
    c = f["close"]
    f["ema_fast"] = ema(c, s.ema_fast)
    f["ema_slow"] = ema(c, s.ema_slow)
    f["rsi"] = rsi(c, 14)
    f["macd_hist"] = macd_hist(c)
    f["atr"] = atr(f, s.atr_period)
    f["atr_pct"] = f["atr"] / c
    f["prior_high"] = f["high"].shift(1).rolling(s.breakout_lookback, min_periods=s.breakout_lookback).max()
    f["volume_ratio"] = f["volume"] / f["volume"].shift(1).rolling(20, min_periods=20).mean()
    f["ret_24h"] = c.pct_change(6)
    f["ret_7d"] = c.pct_change(42)
    f["volume_usd_24h"] = (c * f["volume"]).rolling(6, min_periods=6).sum()
    f["high_30d"] = f["high"].rolling(180, min_periods=30).max()
    return f

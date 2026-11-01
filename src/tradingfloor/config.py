"""All tunable numbers in one place.

The strategy and risk parameters below were fixed before the backtest was run and are not optimised on it.
Changing them after looking at results would turn the backtest into curve fitting, so the README reports
the fee-sensitivity and ablation runs instead of a parameter sweep.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Liquid Coinbase USD pairs. Stablecoins and wrapped tokens are excluded on purpose.
UNIVERSE: list[str] = [
    "BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "LTC",
    "BCH", "UNI", "ATOM", "XLM", "AAVE", "NEAR", "FIL", "ETC", "ALGO", "ICP",
]  # fmt: skip

COIN_NAMES: dict[str, str] = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "XRP": "XRP", "ADA": "Cardano", "DOGE": "Dogecoin",
    "AVAX": "Avalanche", "LINK": "Chainlink", "DOT": "Polkadot", "LTC": "Litecoin", "BCH": "Bitcoin Cash",
    "UNI": "Uniswap", "ATOM": "Cosmos", "XLM": "Stellar", "AAVE": "Aave", "NEAR": "NEAR Protocol",
    "FIL": "Filecoin", "ETC": "Ethereum Classic", "ALGO": "Algorand", "ICP": "Internet Computer",
}  # fmt: skip


class StrategyConfig(BaseModel):
    """Strategy floor: trend-following breakout on 4-hour bars, long only (spot)."""

    ema_fast: int = 50
    ema_slow: int = 200
    breakout_lookback: int = 20  # close above the highest high of the previous N bars
    rsi_min: float = 55.0
    rsi_max: float = 80.0  # skip blow-off moves
    volume_ratio_min: float = 1.5  # last bar volume vs 20-bar average
    atr_period: int = 14
    stop_atr: float = 2.0  # initial stop = entry - 2 ATR
    take_profit_r: float = 4.0  # final target, in multiples of the initial risk (R)
    breakeven_r: float = 2.0  # move the stop to entry once price reaches +2R
    trail_atr: float = 3.0  # trailing stop = highest close - 3 ATR


class RiskConfig(BaseModel):
    """Risk manager: every rule is a hard check, so a failing check blocks the trade."""

    risk_per_trade: float = 0.01  # lose at most 1% of equity if the stop is hit
    max_position_pct: float = 0.20  # no single position above 20% of equity
    max_open_positions: int = 5
    max_total_open_risk: float = 0.05  # sum of (entry - stop) * units across positions
    daily_loss_limit: float = 0.03  # no new entries after a 3% loss from the start of the UTC day
    min_volume_usd_24h: float = 5_000_000
    max_atr_pct: float = 0.08  # 4h ATR above 8% of price is too volatile to size sensibly
    min_reward_risk: float = 2.0
    regime_filter: bool = True  # only buy while BTC trades above its 200-bar EMA
    cooldown_bars_after_stop: int = 6  # 6 x 4h = one day before re-entering a coin that was stopped out
    min_notional_usd: float = 50.0


class CostConfig(BaseModel):
    fee_rate: float = 0.001  # 0.10% per side (exchange taker fee for a modest-volume account)
    slippage_rate: float = 0.0005  # 0.05% per side


class TestingConfig(BaseModel):
    """Testing floor: replay the exact rule on the coin's own past before trusting it."""

    lookback_days: int = 365
    max_hold_bars: int = 60  # 60 x 4h = 10 days; replayed trades still open after that exit at the close
    min_trades_coin: int = 8  # enough trades on this coin to judge it on its own
    min_trades_pool: int = 30  # otherwise fall back to the whole universe
    min_expectancy_r: float = 0.10  # average result per trade, after costs, in units of initial risk


class LLMConfig(BaseModel):
    enabled: bool = True
    # "advisory": the LLM writes the thesis and its verdict is logged, but it cannot block a trade.
    # "veto": a reject (or low confidence) blocks the trade. The anonymised ablation (results/llm_ablation.md) found
    # the setups the LLM vetoed did *better* than the ones it approved, so the live firm runs in advisory mode.
    review_mode: Literal["advisory", "veto"] = "advisory"
    route: str = "smart"  # gateway route: gpt-oss-120b -> gpt-oss-20b
    max_reviews_per_cycle: int = 3
    fail_closed: bool = True  # veto mode: if the strategy floor cannot get an LLM review, the idea waits
    veto_confidence_below: int = 40  # LLM verdict "reject" or confidence under 40 -> veto


class FloorConfig(BaseModel):
    universe: list[str] = Field(default_factory=lambda: list(UNIVERSE))
    starting_cash: float = 10_000.0
    decision_hours: int = 4  # new entries are only considered on a completed 4-hour bar
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    testing: TestingConfig = Field(default_factory=TestingConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    costs: CostConfig = Field(default_factory=CostConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)

# Backtest

2024-11-01 to 2026-11-01, 20 coins, hourly bars, fills at the next bar's open with fees and slippage. Parameters were fixed before this run.

| System | Return | CAGR | Sharpe | Max drawdown | Trades (win rate, avg R) |
|---|---|---|---|---|---|
| full firm (rules, no LLM) | -4.3% | -2.2% | -0.04 | -25.1% | 175 (29%, -0.02R) |
| without testing floor | +5.7% | +2.8% | 0.24 | -30.4% | 286 (31%, +0.04R) |
| without risk floor | -12.8% | -6.6% | -0.14 | -45.1% | 203 (28%, -0.07R) |
| without testing and risk | +1.1% | +0.6% | 0.17 | -45.1% | 361 (31%, +0.03R) |
| full firm, retail fees (0.6%) | -27.3% | -14.8% | -1.09 | -34.9% | 113 (26%, -0.31R) |
| BTC buy & hold | +10.1% | +4.9% | 0.33 | -53.9% |  |
| equal-weight buy & hold (20 coins) | -19.2% | -10.1% | 0.22 | -76.7% |  |

Where ideas stopped (full firm):

| Floor : outcome | Ideas |
|---|---|
| strategy:reject | 765 |
| testing:reject | 277 |
| control:trade | 175 |
| risk:wait | 174 |
| testing:wait | 160 |
| risk:reject | 25 |

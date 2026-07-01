"""Portfolio performance metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd


# 绩效指标函数保持独立，后续阶段会接入回测结果报告。
def annualized_return(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Calculate annualized return from periodic returns."""
    returns = returns.dropna()
    if returns.empty:
        return float("nan")
    total_return = float((1 + returns).prod())
    years = len(returns) / periods_per_year
    return total_return ** (1 / years) - 1


def max_drawdown(nav: pd.Series) -> float:
    """Calculate maximum drawdown from a net asset value series."""
    nav = nav.dropna()
    if nav.empty:
        return float("nan")
    drawdown = nav / nav.cummax() - 1
    return float(drawdown.min())


def sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """Calculate annualized Sharpe ratio."""
    excess = returns.dropna() - risk_free_rate / periods_per_year
    volatility = excess.std(ddof=1)
    if volatility == 0 or np.isnan(volatility):
        return float("nan")
    return float(excess.mean() / volatility * np.sqrt(periods_per_year))

"""Factor calculation functions."""

from __future__ import annotations

import pandas as pd


def momentum(close: pd.Series, window: int = 20) -> pd.Series:
    """Calculate trailing return over a lookback window."""
    return close.pct_change(window)


def reversal(close: pd.Series, window: int = 5) -> pd.Series:
    """Calculate short-term reversal as negative trailing return."""
    return -close.pct_change(window)


def volatility(close: pd.Series, window: int = 20) -> pd.Series:
    """Calculate rolling volatility from daily returns."""
    return close.pct_change().rolling(window).std()

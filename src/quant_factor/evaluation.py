"""Factor evaluation utilities."""

from __future__ import annotations

import pandas as pd


def rank_ic(factor: pd.Series, forward_return: pd.Series) -> float:
    """Calculate Spearman rank IC for one cross-section."""
    aligned = pd.concat([factor, forward_return], axis=1).dropna()
    if aligned.empty:
        return float("nan")
    return float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1], method="spearman"))

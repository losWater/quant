"""Data loading and cleaning entry points."""

from __future__ import annotations

import pandas as pd


def clean_price_data(data: pd.DataFrame) -> pd.DataFrame:
    """Return a basic cleaned price DataFrame.

    The full project will add adjusted prices, suspension handling, listing-age
    filters, and trading-calendar alignment here.
    """
    return data.sort_index().copy()

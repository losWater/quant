"""Shared schema utilities for market data adapters."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

PRICE_COLUMNS = [
    "trade_date",
    "symbol",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "amount",
    "market",
    "source",
]

NUMERIC_PRICE_COLUMNS = [
    "open",
    "close",
    "high",
    "low",
    "volume",
    "amount",
]

UNIVERSE_COLUMNS = [
    "effective_date",
    "index_code",
    "index_name",
    "symbol",
    "name",
    "exchange",
]


def normalize_symbol(value: object) -> str:
    """Normalize a symbol for cross-market usage."""
    raw = str(value).strip().upper()
    root = raw.split(".")[0]
    if root.isdigit():
        return root.zfill(6)
    return raw


def build_manual_universe(symbols: Iterable[str]) -> pd.DataFrame:
    """Build a manual universe DataFrame from configured symbols."""
    normalized_symbols = [normalize_symbol(symbol) for symbol in symbols]
    return pd.DataFrame(
        {
            "symbol": normalized_symbols,
            "name": normalized_symbols,
            "exchange": "manual",
        }
    )


def standardize_price_frame(
    data: pd.DataFrame,
    *,
    market: str,
    source: str,
) -> pd.DataFrame:
    """Normalize already-renamed OHLCV data to the project price schema."""
    result = data.copy()
    required = {"trade_date", "symbol", "open", "close", "high", "low", "volume"}
    missing = required - set(result.columns)
    if missing:
        raise ValueError(f"Price data is missing required columns: {sorted(missing)}")

    if "amount" not in result:
        result["amount"] = pd.NA
    result["market"] = market
    result["source"] = source
    result = result.loc[:, PRICE_COLUMNS].copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    result["symbol"] = result["symbol"].map(normalize_symbol)
    for column in NUMERIC_PRICE_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def standardize_universe_frame(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize universe data to project columns."""
    result = data.copy()
    required = {"symbol", "name"}
    missing = required - set(result.columns)
    if missing:
        raise ValueError(f"Universe data is missing required columns: {sorted(missing)}")

    columns = [column for column in UNIVERSE_COLUMNS if column in result]
    result = result.loc[:, columns].copy()
    result["symbol"] = result["symbol"].map(normalize_symbol)
    if "effective_date" in result:
        result["effective_date"] = pd.to_datetime(result["effective_date"], errors="coerce")
    return result.drop_duplicates(subset=["symbol"]).sort_values("symbol").reset_index(drop=True)

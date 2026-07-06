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
    # 设计思路：
    # 不同市场的数据源对股票代码的写法不一致。A 股可能是 600519.SH，
    # 美股通常是 AAPL。后续模块如果到处判断这些格式，会很混乱。
    # 所以在数据入口统一股票代码，后面的因子、回测都只处理一种干净格式。
    raw = str(value).strip().upper()
    root = raw.split(".")[0]
    if root.isdigit():
        return root.zfill(6)
    return raw


def build_manual_universe(symbols: Iterable[str]) -> pd.DataFrame:
    """Build a manual universe DataFrame from configured symbols."""
    # 美股起步阶段先用手动股票池，不急着接指数历史成分股。
    # 这不是最终严谨方案，但很适合先把工程闭环跑通，并把幸存者偏差写进文档。
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
    # 这一层是数据适配层的核心“契约”：
    # 无论外部接口来自 yfinance、AkShare，还是以后新增港股/其他数据源，
    # 只要最后能输出 PRICE_COLUMNS，后面的量化计算就不用关心数据源差异。
    # 这个设计是为了避免“后端策略代码里到处写 if source == ...”。
    result = data.copy()
    required = {"trade_date", "symbol", "open", "close", "high", "low", "volume"}
    missing = required - set(result.columns)
    if missing:
        raise ValueError(f"Price data is missing required columns: {sorted(missing)}")

    if "amount" not in result:
        # 有些数据源没有成交额。对当前价格类因子来说 amount 不是必需字段，
        # 但保留列位可以让 CSV schema 稳定，后续扩展成交额/流动性因子也方便。
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
    # 股票池也做统一 schema，是因为“选哪些股票”本身就是回测假设的一部分。
    # 如果未来要换成历史指数成分股，这里可以继续扩展 effective_date 等字段。
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

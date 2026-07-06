"""yfinance data source adapter."""

from __future__ import annotations

import pandas as pd

from quant_factor.data_sources.schema import normalize_symbol, standardize_price_frame


def standardize_yfinance_price_data(data: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Normalize yfinance daily price data to project columns."""
    # yfinance 返回英文字段，直接映射为项目内部统一格式。
    # 有时 yfinance 会返回 MultiIndex 列，尤其是一次请求多个 ticker 时；
    # 即便当前是一只一只下载，也保留兼容逻辑，避免以后扩展批量下载时踩坑。
    if isinstance(data.columns, pd.MultiIndex):
        data = data.droplevel(-1, axis=1)
    result = data.reset_index().rename(
        columns={
            "Date": "trade_date",
            "Datetime": "trade_date",
            "Open": "open",
            "Close": "close",
            "High": "high",
            "Low": "low",
            "Volume": "volume",
        }
    )
    result["symbol"] = normalize_symbol(symbol)
    return standardize_price_frame(result, market="us_equity", source="yfinance")


def fetch_yfinance_history(
    symbol: str,
    *,
    start_date: str,
    end_date: str,
    adjusted_price: str,
    timeout: float | None = None,
) -> pd.DataFrame:
    """Fetch one US stock's daily price history from yfinance."""
    import yfinance as yf

    # yfinance 的 end 是开区间，所以这里加一天，确保配置里的结束日被覆盖。
    # 这个细节很容易漏：如果不加一天，配置的 end_date 当天数据不会被下载。
    end_exclusive = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    auto_adjust = adjusted_price in {"auto", "adj", "adjusted", True}
    raw = yf.download(
        normalize_symbol(symbol),
        start=pd.Timestamp(start_date).strftime("%Y-%m-%d"),
        end=end_exclusive,
        auto_adjust=auto_adjust,
        progress=False,
        threads=False,
        timeout=timeout,
    )
    if raw.empty:
        raise ValueError(f"No yfinance data returned for {symbol}")
    return standardize_yfinance_price_data(raw, symbol)

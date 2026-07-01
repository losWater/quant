"""AkShare A-share data source adapter."""

from __future__ import annotations

import pandas as pd

from quant_factor.data_sources.schema import (
    normalize_symbol,
    standardize_price_frame,
    standardize_universe_frame,
)

RAW_PRICE_COLUMNS = {
    "日期": "trade_date",
    "股票代码": "symbol",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_change",
    "涨跌额": "change_amount",
    "换手率": "turnover_rate",
}

UNIVERSE_COLUMNS = {
    "日期": "effective_date",
    "指数代码": "index_code",
    "指数名称": "index_name",
    "成分券代码": "symbol",
    "成分券名称": "name",
    "交易所": "exchange",
    "品种代码": "symbol",
    "品种名称": "name",
    "纳入日期": "effective_date",
}

AKSHARE_EXTRA_COLUMNS = ["amplitude", "pct_change", "change_amount", "turnover_rate"]


def normalize_date(value: str) -> str:
    """Normalize a config date into the YYYYMMDD format expected by AkShare."""
    return pd.Timestamp(value).strftime("%Y%m%d")


def to_tencent_symbol(symbol: str) -> str:
    """Convert a six-digit A-share symbol to Tencent's sh/sz symbol format."""
    normalized = normalize_symbol(symbol)
    if normalized.startswith(("5", "6", "9")):
        return f"sh{normalized}"
    return f"sz{normalized}"


def standardize_universe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize CSI index constituent data returned by AkShare."""
    # 股票池接口可能来自中证或新浪，先统一列名，再保留项目需要的字段。
    renamed = data.rename(columns=UNIVERSE_COLUMNS).copy()
    return standardize_universe_frame(renamed)


def standardize_akshare_price_data(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw AkShare daily price data to project column names and types."""
    # 行情原始字段是中文，这里统一成英文列名和稳定的数据类型。
    renamed = data.rename(columns=RAW_PRICE_COLUMNS).copy()
    result = standardize_price_frame(renamed, market="cn_a_share", source="akshare")
    for column in AKSHARE_EXTRA_COLUMNS:
        if column in renamed:
            result[column] = pd.to_numeric(renamed[column], errors="coerce")
    return result


def standardize_tencent_price_data(data: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Normalize AkShare Tencent daily price data to project columns."""
    # 腾讯接口字段较少，amount 更接近成交量含义；成交额字段先留空。
    result = data.rename(
        columns={
            "date": "trade_date",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "amount": "volume",
        }
    ).copy()
    result["symbol"] = normalize_symbol(symbol)
    return standardize_price_frame(result, market="cn_a_share", source="akshare_tx")


def fetch_csi300_universe(index_code: str = "000300") -> pd.DataFrame:
    """Fetch the latest CSI 300 constituents from AkShare."""
    import akshare as ak

    # 优先使用中证指数接口，失败时回退到新浪接口，降低单一数据源故障影响。
    try:
        data = ak.index_stock_cons_csindex(symbol=index_code)
    except Exception:
        data = ak.index_stock_cons(symbol=index_code)
    return standardize_universe(data)


def fetch_stock_history(
    symbol: str,
    *,
    start_date: str,
    end_date: str,
    adjust: str,
    timeout: float | None = None,
) -> pd.DataFrame:
    """Fetch one stock's adjusted daily price history from AkShare."""
    import akshare as ak

    # AkShare 日线接口要求日期是 YYYYMMDD，复权方式由 config.yaml 控制。
    try:
        raw = ak.stock_zh_a_hist(
            symbol=normalize_symbol(symbol),
            period="daily",
            start_date=normalize_date(start_date),
            end_date=normalize_date(end_date),
            adjust=adjust,
            timeout=timeout,
        )
        return standardize_akshare_price_data(raw)
    except Exception as primary_error:
        # 东方财富接口偶尔会断连，腾讯接口作为备用数据源保证全量流程可继续。
        try:
            fallback = ak.stock_zh_a_hist_tx(
                symbol=to_tencent_symbol(symbol),
                start_date=normalize_date(start_date),
                end_date=normalize_date(end_date),
                adjust=adjust,
            )
            return standardize_tencent_price_data(fallback, symbol)
        except Exception as fallback_error:
            raise RuntimeError(
                f"eastmoney failed: {primary_error}; tencent failed: {fallback_error}"
            ) from fallback_error

"""Data loading and cleaning entry points for A-share daily prices."""

from __future__ import annotations

import argparse
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from quant_factor.config import load_config

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

NUMERIC_PRICE_COLUMNS = [
    "open",
    "close",
    "high",
    "low",
    "volume",
    "amount",
    "amplitude",
    "pct_change",
    "change_amount",
    "turnover_rate",
]


# 基础格式化：把外部数据源里的日期和股票代码统一成项目内部格式。
def normalize_date(value: str) -> str:
    """Normalize a config date into the YYYYMMDD format expected by AkShare."""
    return pd.Timestamp(value).strftime("%Y%m%d")


def normalize_symbol(value: object) -> str:
    """Normalize a symbol for the configured market."""
    raw = str(value).strip().upper()
    root = raw.split(".")[0]
    if root.isdigit():
        return root.zfill(6)
    return raw


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
    required = {"symbol", "name"}
    missing = required - set(renamed.columns)
    if missing:
        raise ValueError(f"Universe data is missing required columns: {sorted(missing)}")

    preferred_columns = [
        "effective_date",
        "index_code",
        "index_name",
        "symbol",
        "name",
        "exchange",
    ]
    columns = [column for column in preferred_columns if column in renamed]
    result = renamed.loc[:, columns].copy()
    result["symbol"] = result["symbol"].map(normalize_symbol)
    if "effective_date" in result:
        result["effective_date"] = pd.to_datetime(result["effective_date"], errors="coerce")
    return result.drop_duplicates(subset=["symbol"]).sort_values("symbol").reset_index(drop=True)


def standardize_price_data(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw AkShare daily price data to project column names and types."""
    # 行情原始字段是中文，这里统一成英文列名和稳定的数据类型。
    renamed = data.rename(columns=RAW_PRICE_COLUMNS).copy()
    required = {"trade_date", "symbol", "open", "close", "high", "low", "volume", "amount"}
    missing = required - set(renamed.columns)
    if missing:
        raise ValueError(f"Price data is missing required columns: {sorted(missing)}")

    columns = [
        "trade_date",
        "symbol",
        *[column for column in NUMERIC_PRICE_COLUMNS if column in renamed],
    ]
    result = renamed.loc[:, columns].copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    result["symbol"] = result["symbol"].map(normalize_symbol)
    for column in NUMERIC_PRICE_COLUMNS:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
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
    if "amount" not in result:
        result["amount"] = pd.NA
    columns = ["trade_date", "symbol", "open", "close", "high", "low", "volume", "amount"]
    return standardize_price_data(result.loc[:, columns])


def standardize_yfinance_price_data(data: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Normalize yfinance daily price data to project columns."""
    # yfinance 返回英文字段，直接映射为项目内部统一格式。
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
    result["amount"] = pd.NA
    columns = ["trade_date", "symbol", "open", "close", "high", "low", "volume", "amount"]
    return standardize_price_data(result.loc[:, columns])


def clean_price_data(data: pd.DataFrame, *, exclude_suspended: bool = True) -> pd.DataFrame:
    """Clean standardized daily price data.

    The current pass covers the first production rules: stable types, duplicate
    removal, chronological ordering, and optional suspended-day filtering.
    """
    # 清洗层只处理通用数据质量问题，不在这里做任何策略判断。
    cleaned = standardize_price_data(data) if "日期" in data.columns else data.copy()
    required = {"trade_date", "symbol", "open", "close", "high", "low", "volume", "amount"}
    missing = required - set(cleaned.columns)
    if missing:
        raise ValueError(f"Cleaned price data is missing required columns: {sorted(missing)}")

    cleaned["trade_date"] = pd.to_datetime(cleaned["trade_date"], errors="coerce")
    cleaned["symbol"] = cleaned["symbol"].map(normalize_symbol)
    for column in NUMERIC_PRICE_COLUMNS:
        if column in cleaned:
            cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")

    cleaned = cleaned.dropna(subset=["trade_date", "symbol", "open", "close", "high", "low"])
    if exclude_suspended and "volume" in cleaned:
        cleaned = cleaned[cleaned["volume"] > 0]

    return (
        cleaned.drop_duplicates(subset=["symbol", "trade_date"], keep="last")
        .sort_values(["symbol", "trade_date"])
        .reset_index(drop=True)
    )


def fetch_csi300_universe(index_code: str = "000300") -> pd.DataFrame:
    """Fetch the latest CSI 300 constituents from AkShare."""
    import akshare as ak

    # 优先使用中证指数接口，失败时回退到新浪接口，降低单一数据源故障影响。
    try:
        data = ak.index_stock_cons_csindex(symbol=index_code)
    except Exception:
        data = ak.index_stock_cons(symbol=index_code)
    return standardize_universe(data)


def build_manual_universe(symbols: Iterable[str]) -> pd.DataFrame:
    """Build a manual universe DataFrame from configured symbols."""
    # 美股先使用手动股票池，避免一开始就引入指数历史成分股数据源。
    normalized_symbols = [normalize_symbol(symbol) for symbol in symbols]
    return pd.DataFrame(
        {
            "symbol": normalized_symbols,
            "name": normalized_symbols,
            "exchange": "manual",
        }
    )


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
        return standardize_price_data(raw)
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


def _write_csv(data: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(path, index=False)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"symbol": "string"})


def load_or_fetch_universe(config: dict[str, Any], *, refresh: bool = False) -> pd.DataFrame:
    """Load the cached universe or fetch it from AkShare."""
    # 股票池写入 raw 目录。默认优先读缓存，避免每次运行都请求网络。
    raw_dir = Path(config["data"]["raw_dir"])
    provider = config["data"].get("provider", "akshare")
    universe_name = config["data"].get("universe", "csi300")
    cache_path = raw_dir / f"universe_{universe_name}.csv"

    if cache_path.exists() and not refresh:
        return standardize_universe(_read_csv(cache_path))

    if provider == "yfinance":
        universe = build_manual_universe(config["data"].get("symbols", []))
    else:
        index_code = "000300" if universe_name == "csi300" else universe_name
        universe = fetch_csi300_universe(index_code=index_code)
    _write_csv(universe, cache_path)
    return universe


def load_or_fetch_price_history(
    symbol: str,
    config: dict[str, Any],
    *,
    refresh: bool = False,
) -> pd.DataFrame:
    """Load one stock's cached price history or fetch it from AkShare."""
    # 单只股票一个 CSV，后续增量更新或定位脏数据会更容易。
    data_config = config["data"]
    raw_dir = Path(data_config["raw_dir"])
    price_dir = raw_dir / "prices"
    symbol = normalize_symbol(symbol)
    cache_path = price_dir / f"{symbol}.csv"

    if cache_path.exists() and not refresh:
        return standardize_price_data(_read_csv(cache_path))

    retries = int(data_config.get("request_retries", 3))
    sleep_seconds = float(data_config.get("request_sleep_seconds", 0.5))
    timeout = data_config.get("request_timeout")
    timeout = float(timeout) if timeout is not None else None

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if data_config.get("provider") == "yfinance":
                data = fetch_yfinance_history(
                    symbol,
                    start_date=data_config["start_date"],
                    end_date=data_config["end_date"],
                    adjusted_price=data_config.get("adjusted_price", "auto"),
                    timeout=timeout,
                )
            else:
                data = fetch_stock_history(
                    symbol,
                    start_date=data_config["start_date"],
                    end_date=data_config["end_date"],
                    adjust=data_config.get("adjusted_price", ""),
                    timeout=timeout,
                )
            _write_csv(data, cache_path)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            return data
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                wait_seconds = sleep_seconds * attempt
                print(
                    f"[data] retry {symbol} attempt {attempt + 1}/{retries} after {exc}",
                    flush=True,
                )
                if wait_seconds > 0:
                    time.sleep(wait_seconds)

    assert last_error is not None
    raise last_error


def build_price_dataset(
    config: dict[str, Any],
    *,
    symbols: Iterable[str] | None = None,
    limit: int | None = None,
    refresh: bool = False,
    continue_on_error: bool = True,
) -> pd.DataFrame:
    """Build and persist the cleaned daily price dataset."""
    # 主流程：股票池 -> 单票行情 -> 合并清洗 -> 输出 processed 数据集。
    universe = load_or_fetch_universe(config, refresh=refresh)
    selected_symbols = [normalize_symbol(symbol) for symbol in (symbols or universe["symbol"])]
    if limit is not None:
        selected_symbols = selected_symbols[:limit]

    frames = []
    failures = []
    total = len(selected_symbols)
    for index, symbol in enumerate(selected_symbols, start=1):
        print(f"[data] {index}/{total} loading {symbol}", flush=True)
        try:
            frames.append(load_or_fetch_price_history(symbol, config, refresh=refresh))
        except Exception as exc:
            failures.append({"symbol": symbol, "error": str(exc)})
            print(f"[data] failed {symbol}: {exc}", flush=True)
            if not continue_on_error:
                raise

    processed_dir = Path(config["data"]["processed_dir"])
    if failures:
        _write_csv(pd.DataFrame(failures), processed_dir / "download_failures.csv")
    elif (processed_dir / "download_failures.csv").exists():
        (processed_dir / "download_failures.csv").unlink()

    if not frames:
        raise RuntimeError("No price data was downloaded or loaded.")

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    cleaned = clean_price_data(
        combined,
        exclude_suspended=config.get("filters", {}).get("exclude_suspended", True),
    )

    processed_path = processed_dir / "daily_prices.csv"
    _write_csv(cleaned, processed_path)
    return cleaned


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and clean A-share daily price data.")
    parser.add_argument("--config", default="config.yaml", help="Path to project config YAML.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of symbols for a smoke run.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        help="Explicit symbols to download, e.g. 000001 600519.",
    )
    parser.add_argument("--refresh", action="store_true", help="Ignore local raw-data cache.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    data = build_price_dataset(
        config,
        symbols=args.symbols,
        limit=args.limit,
        refresh=args.refresh,
    )
    output_path = Path(config["data"]["processed_dir"]) / "daily_prices.csv"
    symbol_count = data["symbol"].nunique() if not data.empty else 0
    print(f"Saved {len(data)} rows for {symbol_count} symbols to {output_path}")


if __name__ == "__main__":
    main()

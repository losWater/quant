"""Data loading and cleaning entry points for A-share daily prices."""

from __future__ import annotations

import argparse
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


def normalize_date(value: str) -> str:
    """Normalize a config date into the YYYYMMDD format expected by AkShare."""
    return pd.Timestamp(value).strftime("%Y%m%d")


def normalize_symbol(value: object) -> str:
    """Normalize an A-share symbol to six digits."""
    return str(value).strip().split(".")[0].zfill(6)


def standardize_universe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize CSI index constituent data returned by AkShare."""
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


def clean_price_data(data: pd.DataFrame, *, exclude_suspended: bool = True) -> pd.DataFrame:
    """Clean standardized daily price data.

    The current pass covers the first production rules: stable types, duplicate
    removal, chronological ordering, and optional suspended-day filtering.
    """
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
) -> pd.DataFrame:
    """Fetch one stock's adjusted daily price history from AkShare."""
    import akshare as ak

    raw = ak.stock_zh_a_hist(
        symbol=normalize_symbol(symbol),
        period="daily",
        start_date=normalize_date(start_date),
        end_date=normalize_date(end_date),
        adjust=adjust,
    )
    return standardize_price_data(raw)


def _write_csv(data: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(path, index=False)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"symbol": "string"})


def load_or_fetch_universe(config: dict[str, Any], *, refresh: bool = False) -> pd.DataFrame:
    """Load the cached universe or fetch it from AkShare."""
    raw_dir = Path(config["data"]["raw_dir"])
    universe_name = config["data"].get("universe", "csi300")
    index_code = "000300" if universe_name == "csi300" else universe_name
    cache_path = raw_dir / f"universe_{universe_name}.csv"

    if cache_path.exists() and not refresh:
        return standardize_universe(_read_csv(cache_path))

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
    data_config = config["data"]
    raw_dir = Path(data_config["raw_dir"])
    price_dir = raw_dir / "prices"
    symbol = normalize_symbol(symbol)
    cache_path = price_dir / f"{symbol}.csv"

    if cache_path.exists() and not refresh:
        return standardize_price_data(_read_csv(cache_path))

    data = fetch_stock_history(
        symbol,
        start_date=data_config["start_date"],
        end_date=data_config["end_date"],
        adjust=data_config.get("adjusted_price", ""),
    )
    _write_csv(data, cache_path)
    return data


def build_price_dataset(
    config: dict[str, Any],
    *,
    symbols: Iterable[str] | None = None,
    limit: int | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    """Build and persist the cleaned daily price dataset."""
    universe = load_or_fetch_universe(config, refresh=refresh)
    selected_symbols = [normalize_symbol(symbol) for symbol in (symbols or universe["symbol"])]
    if limit is not None:
        selected_symbols = selected_symbols[:limit]

    frames = [
        load_or_fetch_price_history(symbol, config, refresh=refresh)
        for symbol in selected_symbols
    ]
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    cleaned = clean_price_data(
        combined,
        exclude_suspended=config.get("filters", {}).get("exclude_suspended", True),
    )

    processed_path = Path(config["data"]["processed_dir"]) / "daily_prices.csv"
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
